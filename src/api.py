import aiohttp
from mautrix.client import ClientAPI
import markdown

from log import getlogger

logger = getlogger()


async def send_message_as_tool(
    tool_id,
    tool_input,
    room_id,
    event_id,
    thread=None,
    workflow_bot=None,
    msg_limit=0,
    session_id=None
):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://bots.spaceship.im/agents/{tool_id}") as result:
            if result.status_code == 200:
                data = await result.json()
                access_token = data['access_token']
            else:
                raise Exception(f"Access token missing: {tool_id}")
    content = {
        "body": tool_input,
        "msgtype": "m.text",
        "format": "org.matrix.custom.html",
        "formatted_body": markdown.markdown(
            tool_input,
            extensions=["nl2br", "tables", "fenced_code"]
        ),
        "message_limit": {
            "workflow_bot": workflow_bot,
            "limit": msg_limit,
        },
        "session_id": session_id

    }
    if thread is None:
        thread = {
            'm.in_reply_to': {'event_id': event_id}
        }
    content["m.relates_to"] = thread
    try:
        client = ClientAPI(base_url="https://matrix.spaceship.im",
                       token=access_token)
        event_id = await client.send_message(room_id, content)
    except Exception as e:
        logger.error(f"sub agent bot error: {e}")
    return event_id, access_token


async def edit_message(event_id, access_token, msg, room_id, workflow_bot, msg_limit, session_id):
    content = {
        "body": f" * {msg}",
        "msgtype": "m.text",
        "m.new_content": {
            "body": msg,
            "msgtype": "m.text",
            "format": "org.matrix.custom.html",
            "formatted_body": markdown.markdown(
                msg,
                extensions=["nl2br", "tables", "fenced_code"]
            )
        },
        "message_limit": {
        "workflow_bot": workflow_bot,
        "limit": msg_limit,
        },
        "session_id": session_id,
        "format": "org.matrix.custom.html",
        "formatted_body": f" * {msg}",
        "m.relates_to": {
            "event_id": event_id,
            "rel_type": "m.replace"
        }
    }
    try:
        client = ClientAPI(base_url="https://matrix.spaceship.im",
                       token=access_token)
        event_id = await client.send_message(room_id, content)
    except Exception as e:
        logger.error(f"edit msg sub bot error :{e}")
    return event_id


async def invite_bot_to_room(tool_id, session):
    result = await session.get(f"https://bots.spaceship.im/agents/{tool_id}")
    if not result.json():
        return None
    return result.json()["bot_username"]

async def enable_api(conn, userId, session):
    try:
        email_id = await session.get(f"https://bots.spaceship.im/user/{userId}")
        email_id.raise_for_status()
        email = email_id.json()["email"]
        conn.execute(f"INSERT OR REPLACE INTO bot VALUES ('{userId}', '{email}')")
    except Exception as e:
        logger.error(f"email api: {e}")
        return False
    return True

async def intro_message(agent_id, session):
    result = await session.post(f"https://api.spaceship.im/api/v1/bots/{agent_id}/intro")
    if result.status_code == 200:
        return result.json()["data"]
    return None