import logging
from supabase import Client, create_client
import os

logger = logging.getLogger(__name__)


def update_task_status(
    supabase: Client, task_id: str, task_version: int, task_status: int
):
    """
    Updates the task_status in the task_status table.

    Args:
        task_id (str): The ID of the task.
        task_version (str): The version of the task.
        task_status (int): The new status of the task.
    """
    try:
        # Update the task_status table
        data = (
            supabase.table("task_status")
            .update({"task_status": task_status})
            .eq("task_draft_id", task_id)
            .eq("task_draft_version", task_version)
            .execute()
        )

        if data:
            logger.info(
                f"Task status updated successfully for task_id: {task_id}, task_version: {task_version}"
            )
            return True, data

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return False, str(e)


if __name__ == "__main__":
    # Example usage:
    task_id = "your_task_id"  # Replace with an actual task ID
    task_version = 1  # Replace with an actual task version
    new_status = 2  # Replace with the desired task status (e.g., 2 for "in progress")

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if supabase_url is None or supabase_key is None:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    supabase: Client = create_client(supabase_url, supabase_key)

    success, result = update_task_status(supabase, task_id, task_version, new_status)

    if success:
        print("Task status updated successfully.")
        # You can further process the result data if needed
        print(result)
    else:
        print("Task status update failed.")
        print(result)
