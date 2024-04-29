import httpx
import aiohttp
from mautrix.client import ClientAPI
import markdown


async def send_message_as_tool(tool_id, tool_input, room_id, event_id, thread=None, workflow_bot=None, msg_limit=0):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://bots.pixx.co/agents/{tool_id}") as result:
            data = await result.json()
            if not data:
                return None
            else:
                access_token = data['access_token']
    content = {
        "body": tool_input,
        "msgtype": "m.text",
        "format": "org.matrix.custom.html",
        "formatted_body" : markdown.markdown(
            tool_input, 
            extensions=["nl2br", "tables", "fenced_code"]
        ),
        "message_limit" : {
            "workflow_bot" : workflow_bot,
            "limit" : msg_limit,
        }

    }
    if thread is None:
        thread = {
            'm.in_reply_to': {'event_id': event_id}
        }
    content["m.relates_to"] = thread
    client = ClientAPI(base_url="https://matrix.pixx.co",
                       token=access_token)
    await client.send_message(room_id, content)


async def invite_bot_to_room(tool_id, session):
    result = await session.get(f"https://bots.pixx.co/agents/{tool_id}")
    if not result.json():
        return None
    return result.json()["bot_username"]
