import config
import asyncio
import uvicorn
import threading
import httpx
from Telegram_taking_messages import edits_taker, new_message_taker
from Telegram_AI_processor import main_once
from LLM_Suitcase_server import app as llm_app
from SQLite_database import tg_database as db_app

OCCUPIED = False  # Flag to prevent overlap


# Function to run the async main loop for taking messages
async def run_take_messages_loop():
    global OCCUPIED
    while True:
        try:
            while OCCUPIED:
                await asyncio.sleep(2.01)  # Sleep while OCCUPIED is True
            if not OCCUPIED:
                print("Lunching taking messages iteration")
                OCCUPIED = True
                await new_message_taker()  # Run the async loop for new_message_taker
                #print("FINISHED taking messages iteration")
                OCCUPIED = False
            await asyncio.sleep(config.INTERVAL_TO_GATHER)  # Wait before trying again
        except Exception as e:
            print("Error in message taking loop:", e)

# Function to run the async main loop for taking edits
async def run_take_edits_loop():
    global OCCUPIED
    await asyncio.sleep(1.1)
    while True:
        try:
            while OCCUPIED:
                await asyncio.sleep(2.1)  # Sleep while OCCUPIED is True
            if not OCCUPIED:
                print("Lunching editing iteration")
                OCCUPIED = True
                await edits_taker()  # Run the async loop for edits_taker
                #print("FINISHED editing iteration")
                OCCUPIED = False
            await asyncio.sleep(config.INTERVAL_FOR_SCOUT)  # Wait before trying again
        except Exception as e:
            print("Error in message taking loop:", e)


# Function to run the AI processing loop for main_once
async def run_main_once():
    global OCCUPIED
    i = 0
    while True:
        try:
            if not OCCUPIED:
                OCCUPIED = True
                # Run the synchronous main_once() in a separate thread with an event loop
                #print("Started posting iteration")
                await asyncio.to_thread(run_main_once_in_thread)
                print(f"Loop count: {i}")
                i += 1
                OCCUPIED = False
            await asyncio.sleep(5)  # Sleep before checking again
        except Exception as e:
            print("Error in AI processing loop:", e)


# This is the helper function that runs main_once in the background thread
def run_main_once_in_thread():
    # Create a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run the main_once function in the new event loop
    try:
        # Try to run the main_once function inside the new event loop
        loop.run_until_complete(main_once())  # Run the synchronous function inside the new event loop
    except TypeError as e:
        # If a TypeError occurs (due to asyncio.Future or coroutine issue), print the error and continue
        # print(f"Error running main_once: {e}. Continuing with next iteration.")
        pass  # Continue without crashing


def run_llm_server():
    uvicorn.run(
        llm_app,
        host=config.llm_ipaddress,
        port=config.llm_port,
        reload=False,
        log_level="critical"  # only critical errors will print
    )

def run_db_server():
    uvicorn.run(
        db_app,
        host=config.database_ipaddress,
        port=config.database_port,
        reload=False,
        log_level="critical")


async def wait_for_server(url, interval=2):
    while True:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:  # 2-second timeout
                r = await client.get(url)
                if r.status_code == 200:
                    print(f"Server at {url} is up!")
                    return
        except Exception as e:
            print(f"Waiting for {url}... ({e})")
        await asyncio.sleep(interval)

# Main async loop to run both tasks concurrently
async def main_loop():
    threading.Thread(target=run_db_server, daemon=False).start()
    threading.Thread(target=run_llm_server, daemon=False).start()

    await wait_for_server(f"http://{config.llm_ipaddress}:{config.llm_port}/")
    await wait_for_server(f"http://{config.database_ipaddress}:{config.database_port}/health")

    task1 = asyncio.create_task(run_take_messages_loop())  # Async task for message-taking
    task2 = asyncio.create_task(run_take_edits_loop())  # Async task for edits-taking
    task3 = asyncio.create_task(run_main_once())  # Async task for AI processing

    # Wait for both tasks to finish (they run indefinitely, so the program keeps running)
    await asyncio.gather(task1, task2, task3)


if __name__ == "__main__":
    asyncio.run(main_loop())