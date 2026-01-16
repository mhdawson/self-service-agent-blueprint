#!/usr/bin/env python3
"""
Generate audit conversations from production LangGraph threads.

This script retrieves real conversations from the LangGraph checkpoints table
and saves them in the same format as generated test conversations for evaluation.

Usage:
    # Get 10 random threads from last week (time is optional)
    python evaluations/generate-audit-conversations.py \
        --start-date "2026-01-09" \
        --end-date "2026-01-16" \
        --sample-size 10

    # Get specific threads
    python evaluations/generate-audit-conversations.py \
        --thread-ids thread-abc-123 thread-def-456

    # Get all threads from a specific day (omitting time uses 00:00:00 and 23:59:59)
    python evaluations/generate-audit-conversations.py \
        --start-date "2026-01-15" \
        --end-date "2026-01-15" \
        --sample-size 100

    # Use explicit times for precise ranges
    python evaluations/generate-audit-conversations.py \
        --start-date "2026-01-15 09:00:00" \
        --end-date "2026-01-15 17:00:00" \
        --sample-size 50
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver


class AuditConversationGenerator:
    """Generates audit conversations from production LangGraph threads."""

    def __init__(
        self,
        output_dir: Optional[str] = None,
        langgraph_config_dir: Optional[str] = None,
        langgraph_port: int = 2024,
    ):
        """
        Initialize the audit conversation generator.

        Args:
            output_dir: Directory to save conversation JSON files (defaults to evaluations/results/conversation_results/)
            langgraph_config_dir: Directory containing langgraph.json (if using SDK)
            langgraph_port: Port for langgraph dev server
        """
        # Default output directory - always relative to this script's location
        # This works whether running from project root or evaluations directory
        if output_dir is None:
            script_dir = Path(__file__).parent.resolve()
            self.output_dir = script_dir / "results" / "conversation_results"
        else:
            self.output_dir = Path(output_dir).resolve()

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.langgraph_config_dir = langgraph_config_dir
        self.langgraph_port = langgraph_port
        self.langgraph_process = None

        # Database connection from environment
        self.db_config = self._get_db_config()

    def _get_db_config(self) -> Dict[str, str]:
        """Get database configuration from environment."""
        return {
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": os.getenv("POSTGRES_PORT", "5432"),
            "database": os.getenv("POSTGRES_DB", "rag_blueprint"),
            "user": os.getenv("POSTGRES_USER", "postgres"),
            "password": os.getenv("POSTGRES_PASSWORD", "rag_password"),
        }

    def _get_connection_string(self) -> str:
        """Build PostgreSQL connection string."""
        cfg = self.db_config
        return f"postgres://{cfg['user']}:{cfg['password']}@{cfg['host']}:{cfg['port']}/{cfg['database']}"

    def start_langgraph_server(self):
        """Start the langgraph dev server."""
        if not self.langgraph_config_dir:
            print("No langgraph config directory provided, skipping server startup")
            return

        print(f"Starting langgraph dev server on port {self.langgraph_port}...")
        self.langgraph_process = subprocess.Popen(
            ["langgraph", "dev", "--port", str(self.langgraph_port)],
            cwd=self.langgraph_config_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to start
        time.sleep(5)
        print("LangGraph server started")

    def stop_langgraph_server(self):
        """Stop the langgraph dev server."""
        if self.langgraph_process:
            print("Stopping langgraph dev server...")
            self.langgraph_process.terminate()
            self.langgraph_process.wait()
            print("LangGraph server stopped")

    def get_threads_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        sample_size: int,
    ) -> List[Dict]:
        """
        Get random conversation threads within a date range from checkpoints table.

        Args:
            start_date: Start of date range
            end_date: End of date range
            sample_size: Number of threads to randomly sample

        Returns:
            List of thread info with thread_id
        """
        print(f"Querying threads between {start_date} and {end_date}...")

        conn_string = self._get_connection_string()
        conn = psycopg.connect(conn_string, autocommit=True, row_factory=psycopg.rows.dict_row)
        cursor = conn.cursor()

        # Query checkpoints table for distinct thread_ids
        # Use checkpoint timestamp for date filtering (best effort)
        # The checkpoint JSONB has a 'ts' field with timestamp
        query = """
            SELECT c.thread_id,
                   MIN((c.checkpoint->>'ts')::timestamp) as first_checkpoint_ts
            FROM checkpoints c
            WHERE c.checkpoint->>'ts' IS NOT NULL
              AND (c.checkpoint->>'ts')::timestamp BETWEEN %s AND %s
            GROUP BY c.thread_id
            ORDER BY RANDOM()
            LIMIT %s
        """

        cursor.execute(query, (start_date, end_date, sample_size))
        results = cursor.fetchall()

        cursor.close()
        conn.close()

        print(f"Found {len(results)} threads matching criteria")

        return results

    def get_thread_ids_for_session(self, session_id: str) -> List[str]:
        """
        Get all thread IDs associated with a session.

        Args:
            session_id: The session ID

        Returns:
            List of thread IDs (conversation_thread_ids)
        """
        conn_string = self._get_connection_string()
        conn = psycopg.connect(conn_string, autocommit=True, row_factory=psycopg.rows.dict_row)
        cursor = conn.cursor()

        # Get all conversation_thread_ids for this session
        # There might be multiple threads in a session
        query = """
            SELECT DISTINCT conversation_thread_id
            FROM request_sessions
            WHERE session_id = %s
              AND conversation_thread_id IS NOT NULL
            ORDER BY conversation_thread_id
        """

        cursor.execute(query, (session_id,))
        results = cursor.fetchall()

        cursor.close()
        conn.close()

        return [row['conversation_thread_id'] for row in results]

    def get_user_email_for_thread(self, thread_id: str) -> Optional[str]:
        """
        Get the user's email address associated with a thread.

        Args:
            thread_id: The thread ID (conversation_thread_id)

        Returns:
            User email or None if not found
        """
        conn_string = self._get_connection_string()
        conn = psycopg.connect(conn_string, autocommit=True, row_factory=psycopg.rows.dict_row)
        cursor = conn.cursor()

        query = """
            SELECT u.primary_email as user_email
            FROM request_sessions rs
            JOIN users u ON rs.user_id = u.user_id
            WHERE rs.conversation_thread_id = %s
            LIMIT 1
        """

        cursor.execute(query, (thread_id,))
        result = cursor.fetchone()

        cursor.close()
        conn.close()

        return result['user_email'] if result else None

    def get_conversation_from_threads(self, thread_ids: List[str]) -> List[Dict[str, str]]:
        """
        Get conversation messages from multiple threads and combine them chronologically.

        Args:
            thread_ids: List of thread IDs to retrieve

        Returns:
            List of conversation turns with role and content, sorted chronologically
        """
        conn_string = self._get_connection_string()
        conn = psycopg.connect(conn_string, autocommit=True)

        try:
            # Use PostgresSaver to get checkpoints
            checkpointer = PostgresSaver(conn)

            # Collect all messages with timestamps from all threads
            all_messages_with_time = []

            for thread_id in thread_ids:
                # Get the latest checkpoint for this thread
                config = {"configurable": {"thread_id": thread_id}}
                checkpoints = list(checkpointer.list(config, limit=1))

                if not checkpoints:
                    continue

                # Get the checkpoint data
                checkpoint_tuple = checkpoints[0]
                checkpoint = checkpoint_tuple.checkpoint

                # Extract messages from checkpoint
                channel_values = checkpoint.get("channel_values", {})
                messages = channel_values.get("messages", [])

                # Add each message with an index for ordering
                for idx, msg in enumerate(messages):
                    msg_type = type(msg).__name__

                    if msg_type == "HumanMessage":
                        all_messages_with_time.append({
                            "thread_id": thread_id,
                            "index": idx,
                            "role": "user",
                            "content": msg.content
                        })
                    elif msg_type == "AIMessage":
                        # Handle both string content and structured content
                        if isinstance(msg.content, str):
                            content = msg.content
                        elif isinstance(msg.content, list):
                            # Extract text blocks from structured content
                            text_parts = []
                            for block in msg.content:
                                if isinstance(block, dict):
                                    if block.get("type") == "text":
                                        text_parts.append(block.get("text", ""))
                                elif isinstance(block, str):
                                    text_parts.append(block)
                            content = "\n".join(text_parts) if text_parts else str(msg.content)
                        else:
                            content = str(msg.content)

                        if content:  # Only add non-empty assistant messages
                            all_messages_with_time.append({
                                "thread_id": thread_id,
                                "index": idx,
                                "role": "assistant",
                                "content": content
                            })

            # Sort by thread_id and then by index to maintain chronological order
            # Thread IDs are typically chronological, and within each thread messages are ordered
            all_messages_with_time.sort(key=lambda x: (x["thread_id"], x["index"]))

            # Convert to final format without metadata
            conversation = [{"role": msg["role"], "content": msg["content"]}
                          for msg in all_messages_with_time]

            return conversation

        finally:
            conn.close()

    def save_conversation(
        self,
        thread_id: str,
        conversation: List[Dict[str, str]],
        user_email: Optional[str] = None,
        date_str: Optional[str] = None,
        thread_ids: Optional[List[str]] = None,
    ):
        """
        Save conversation to JSON file in the standard format.

        Args:
            thread_id: The thread ID (used as identifier)
            conversation: List of conversation turns
            user_email: The user's email address (optional)
            date_str: Date string for filename (optional)
            thread_ids: List of thread IDs included in this conversation (optional)
        """
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

        # Create output structure matching existing format
        output = {
            "metadata": {
                "authoritative_user_id": user_email or "unknown",
                "description": f"Audit conversation from {date_str} - Thread {thread_id}",
                "thread_id": thread_id,
                "thread_ids": thread_ids or [],
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
            "conversation": conversation
        }

        # Generate filename: audit_YYYYMMDD_threadID.json
        filename = f"audit_{date_str}_{thread_id}.json"
        filepath = self.output_dir / filename

        # Save with proper formatting (2-space indent like existing files)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"Saved conversation to {filepath}")

    def generate_from_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        sample_size: int,
    ):
        """
        Generate audit conversations from a date range.

        Args:
            start_date: Start of date range
            end_date: End of date range
            sample_size: Number of threads to sample
        """
        # Step 1: Query checkpoints table for random threads in date range
        threads = self.get_threads_by_date_range(start_date, end_date, sample_size)

        if not threads:
            print("No threads found in date range")
            return

        # Step 2: For each thread, get conversation and save
        date_str = start_date.strftime("%Y%m%d")

        for i, thread_info in enumerate(threads, 1):
            thread_id = thread_info['thread_id']

            print(f"\nProcessing thread {i}/{len(threads)}: {thread_id}")

            try:
                # Try to get user email from request_sessions (if thread is linked)
                user_email = self.get_user_email_for_thread(thread_id)

                # Get conversation from this thread
                conversation = self.get_conversation_from_threads([thread_id])

                if not conversation:
                    print(f"  Warning: No messages found for thread {thread_id}")
                    continue

                print(f"  Found {len(conversation)} messages")

                # Save to file (using thread_id as identifier)
                self.save_conversation(thread_id, conversation, user_email, date_str, [thread_id])

            except Exception as e:
                print(f"  Error processing thread {thread_id}: {e}")
                continue

    def generate_from_thread_ids(self, thread_ids: List[str]):
        """
        Generate audit conversations from specific thread IDs.
        Each thread ID creates a separate conversation file.

        Args:
            thread_ids: List of thread IDs to retrieve
        """
        print(f"Processing {len(thread_ids)} specific threads...")

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

        for i, thread_id in enumerate(thread_ids, 1):
            print(f"\nProcessing thread {i}/{len(thread_ids)}: {thread_id}")

            try:
                # Get user email from database
                user_email = self.get_user_email_for_thread(thread_id)

                # Get conversation from this single thread
                conversation = self.get_conversation_from_threads([thread_id])

                if not conversation:
                    print(f"  Warning: No messages found for thread {thread_id}")
                    continue

                # Save to file (using thread_id as the identifier)
                self.save_conversation(thread_id, conversation, user_email, date_str, [thread_id])

            except Exception as e:
                print(f"  Error processing thread {thread_id}: {e}")
                continue


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate audit conversations from production LangGraph threads"
    )

    # Mode 1: Date range with sampling
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date (YYYY-MM-DD or 'YYYY-MM-DD HH:MM:SS'). Time defaults to 00:00:00 if omitted.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date (YYYY-MM-DD or 'YYYY-MM-DD HH:MM:SS'). Time defaults to 23:59:59 if omitted.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        help="Number of sessions to randomly select (each session may contain multiple threads)",
    )

    # Mode 2: Specific threads
    parser.add_argument(
        "--thread-ids",
        nargs="+",
        help="One or more thread IDs to retrieve",
    )

    # Optional settings
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for conversation files (default: auto-detected based on script location)",
    )
    parser.add_argument(
        "--langgraph-config-dir",
        type=str,
        help="Directory containing langgraph.json (for starting dev server)",
    )
    parser.add_argument(
        "--langgraph-port",
        type=int,
        default=2024,
        help="Port for langgraph dev server",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.thread_ids:
        # Thread ID mode
        if args.start_date or args.end_date or args.sample_size:
            parser.error("Cannot use --thread-ids with date range options")
    else:
        # Date range mode
        if not (args.start_date and args.end_date and args.sample_size):
            parser.error("Must provide either --thread-ids OR all of (--start-date, --end-date, --sample-size)")

    return args


def parse_datetime(date_str: str, is_end_date: bool = False) -> datetime:
    """
    Parse datetime string in various formats.

    Args:
        date_str: Date string to parse
        is_end_date: If True and only date is provided, use 23:59:59; otherwise use 00:00:00

    Returns:
        Parsed datetime object
    """
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)

            # If only date was provided (YYYY-MM-DD format), add time component
            if fmt == "%Y-%m-%d":
                if is_end_date:
                    # End of day: 23:59:59
                    dt = dt.replace(hour=23, minute=59, second=59)
                # Start of day is already 00:00:00 by default

            return dt
        except ValueError:
            continue

    raise ValueError(f"Could not parse date: {date_str}. Use YYYY-MM-DD or 'YYYY-MM-DD HH:MM:SS'")


def main():
    """Main entry point."""
    args = parse_args()

    # Initialize generator
    generator = AuditConversationGenerator(
        output_dir=args.output_dir,
        langgraph_config_dir=args.langgraph_config_dir,
        langgraph_port=args.langgraph_port,
    )

    try:
        # Start LangGraph server if config directory provided
        if args.langgraph_config_dir:
            generator.start_langgraph_server()

        # Execute based on mode
        if args.thread_ids:
            # Mode 2: Specific thread IDs
            generator.generate_from_thread_ids(args.thread_ids)
        else:
            # Mode 1: Date range with sampling
            start_date = parse_datetime(args.start_date, is_end_date=False)
            end_date = parse_datetime(args.end_date, is_end_date=True)
            generator.generate_from_date_range(start_date, end_date, args.sample_size)

        print("\n✓ Audit conversation generation complete!")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Always stop the server
        if args.langgraph_config_dir:
            generator.stop_langgraph_server()


if __name__ == "__main__":
    main()
