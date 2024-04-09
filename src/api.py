import httpx
import aiohttp
from mautrix.client import ClientAPI
import markdown


async def send_message_as_tool(tool_id, tool_input, room_id, event_id, thread=None):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://bots.pixx.co/agents/{tool_id}") as result:
            if not result.json():
                return None
            else:
                access_token = result.json()['access_token']
    msg = {
        "body": tool_input,
        "msgtype": "m.text",
        "format": "org.matrix.custom.html",
        "formatted_body" : markdown.markdown(
            tool_input, 
            extensions=["nl2br", "tables", "fenced_code"]
        )

    }
    if thread is None:
        thread = {
            'm.in_reply_to': {'event_id': event_id}
        }
    msg["m.relates_to"] = thread
    client = ClientAPI(base_url="https://matrix.pixx.co",
                       token=access_token)
    await client.send_message(room_id, msg)


async def invite_bot_to_room(tool_id, session):
    result = await session.get(f"https://bots.pixx.co/agents/{tool_id}")
    if not result.json():
        return None
    return result.json()["bot_username"]
