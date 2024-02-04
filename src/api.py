import httpx
from mautrix.client import ClientAPI


async def send_message_as_tool(tool_id, tool_input, room_id, event_id, session: httpx.AsyncClient, thread=None):
    result = await session.get(f"https://bots.pixx.co/agents/{tool_id}")
    if result == []:
        return None
    msg = {
        "body": tool_input,
        "msgtype": "m.text"
    }
    if thread is None:
        thread = {
            'm.in_reply_to': {'event_id': event_id}
        }
    msg["m.relates_to"] = thread
    client = ClientAPI(base_url="https://matrix.pixx.co",
                       token=result['access_token'])
    await client.send_message(room_id, msg)


async def invite_bot_to_room(tool_id, session):
    result = await session.get(f"https://bots.pixx.co/agents/{tool_id}")
    if result == []:
        return None
    return result["bot_username"]
