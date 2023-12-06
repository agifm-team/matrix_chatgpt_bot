import httpx
from mautrix.client import ClientAPI

async def send_message_as_tool(tool_name,tool_input,room_id,owner_id,session: httpx.AsyncClient):
    result = await session.get(f"https://bots.multi.so/tools/{tool_name}/user/{owner_id}")
    if result == []:
        return None
    msg = {
        "body" : tool_input,
        "msgtype" : "m.text"
    }
    client = ClientAPI(base_url="https://matrix.multi.so",token=result['token'])
    await client.send_message(room_id, msg)
