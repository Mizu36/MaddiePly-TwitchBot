from db import get_enabled_scheduled_messages, get_scheduled_message, get_setting
from tools import get_reference, debug_print
import asyncio

class MessageScheduler():
    def __init__(self):
        self.tasks = []
        self.shared_chat = False
        self.twitch_bot = get_reference("TwitchBot")
        debug_print("MessageScheduler", "Message scheduler initialized.")
        
    async def start_scheduled_messages(self):
        """Starts all enabled schedules messages, each in their own task."""
        debug_print("MessageScheduler", "Starting scheduled messages...")
        scheduled_messages = await get_enabled_scheduled_messages()
        for message in scheduled_messages:
            message_id = message.get("id")
            text = message.get("message")
            minutes = message.get("minutes", 10)
            messages = message.get("messages", 0)
            task = asyncio.create_task(self.scheduled_message_task(message=text, minutes=minutes, messages=messages, task_id=message_id))
            self.tasks.append({"task_id": message_id, "task": task, "message_count": 0})

    async def start_new_message(self, task_id: int):
        """Accepts primary key of a scheduled message and starts it's timer. Also cancels the task beforehand if called as an update."""
        debug_print("MessageScheduler", "Starting a new standalone scheduled message.")
        scheduled_message = await get_scheduled_message(task_id)
        if scheduled_message:
            text = scheduled_message.get("message")
            minutes = scheduled_message.get("minutes", 10)
            messages = scheduled_message.get("messages", 0)
            # Try to cancel any existing task for this id first
            debug_print("MessageScheduler", f"Attempting to end existing task for id {task_id} before (re)starting")
            await self.end_task(task_id)
            try:
                task = asyncio.create_task(self.scheduled_message_task(message=text, minutes=minutes, messages=messages, task_id=task_id))
                self.tasks.append({"task_id": task_id, "task": task, "message_count": 0})
            except Exception as e:
                debug_print("MessageScheduler", f"Error creating scheduled task for id {task_id}: {e}")
        else:
            debug_print("MessageScheduler", f"Returned object for scheduled message id {task_id} is None.")

    async def scheduled_message_task(self, message, minutes: int, messages: int, task_id: int):
        '''Starts the scheduled message task, adds it to a list of tasks. 
        Keeps track of each message since last sent and waits until both time is up and number of messages received before sending message.'''
        debug_print("MessageScheduler", f"Scheduled message task started for id {task_id}: '{message}' every {minutes} minutes after {messages} messages.")
        while True:
            if self.shared_chat:
                if not await get_setting("Shared Chat Scheduled Messages Enabled", default=False):
                    debug_print("MessageScheduler", "Shared chat is active. Pausing scheduled message task.")
                    await asyncio.sleep(60)
                    continue  # Check every minute if shared chat is still active
            await asyncio.sleep(minutes * 60) #Multiply by 60 to convert to minutes
            debug_print("MessageScheduler", f"Time has elapsed for scheduled message.{f" Waiting for {messages} message{f"s" if messages > 1 else ""} before sending message." if messages > 0 else ""}")
            for task in self.tasks:
                if task["task_id"] == task_id:
                    while task["message_count"] < messages:
                        await asyncio.sleep(5)  # Check every 5 seconds
                    if not self.shared_chat:
                        if not self.twitch_bot:
                            self.twitch_bot = get_reference("TwitchBot")
                        await self.twitch_bot.send_chat(message)
                        debug_print(f"MessageScheduler", f"Scheduled Message Sent: {message}")
                    else:
                        debug_print("MessageScheduler", f"Scheduled Message Skipped (Shared Chat Active): {message}")
                    task["message_count"] = 0  # Reset message count after sending
                    break

    async def increment_message_count(self):
        debug_print("MessageScheduler", "Incrementing message counts for scheduled tasks.")
        for task in self.tasks:
            task["message_count"] += 1

    async def end_task(self, message_id):
        '''Ends a specific scheduled message task by message.'''
        debug_print("MessageScheduler", f"Ending scheduled message task for message id: '{message_id}'")
        removed = False
        for task in list(self.tasks):
            if task["task_id"] == message_id:
                try:
                    t = task.get("task")
                    debug_print("MessageScheduler", f"Cancelling task object for id {message_id}: {t}")
                    t.cancel()
                except Exception as e:
                    debug_print("MessageScheduler", f"Error cancelling task for id {message_id}: {e}")
                try:
                    self.tasks.remove(task)
                    removed = True
                except Exception as e:
                    debug_print("MessageScheduler", f"Error removing task entry for id {message_id}: {e}")
        if not removed:
            debug_print("MessageScheduler", f"No active task found for id {message_id} to cancel.")

    async def reschedule_message(self, old_scheduled_message: dict, new_scheduled_message: dict):
        '''Reschedules a message after its settings have been changed. Accepts the old scheduled message dict and the updated scheduled message dict.'''
        debug_print("MessageScheduler", f"Rescheduling message from '{old_scheduled_message.get('message')}' to '{new_scheduled_message.get('message')}'")
        # First, find and cancel the existing task
        for task in self.tasks:
            if task.get("task_id") == int(old_scheduled_message.get("id")):
                task["task"].cancel()
                self.tasks.remove(task)
                break
        # Now, create a new task with the updated settings
        message_id = new_scheduled_message.get("id")
        text = new_scheduled_message.get("message")
        minutes = new_scheduled_message.get("minutes", 10)
        messages = new_scheduled_message.get("messages", 0)
        task = asyncio.create_task(self.scheduled_message_task(message=text, minutes=minutes, messages=messages, task_id=message_id))
        self.tasks.append({"task_id": message_id, "task": task, "message_count": 0})

    def set_shared_chat(self, value: bool):
        '''Sets the shared chat status.'''
        debug_print("MessageScheduler", f"Setting shared chat to: {value}")
        self.shared_chat = value
