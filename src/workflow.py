import httpx
import aiohttp
import logging

from api import send_message_as_tool


async def workflow_steps(
        superagent_url: str,
        workflow_id: str,
        api_key: str,
        session: httpx.AsyncClient
):
    headers = {
        'Authorization': f'Bearer {api_key}',
    }
    api_url = f"{superagent_url}/api/v1/workflows/{workflow_id}/steps"
    response = await session.get(
        api_url,
        headers=headers,
        timeout=30,
    )
    result = {}
    if response.status_code == 200:
        data = response.json()["data"]
        for agents in data:
            agent_id = agents['agent']['id']
            agent_name = agents['agent']['name']
            result[agent_name] = agent_id

        return result
    return response.json()


async def stream_json_response_with_auth(
    api_url,
    api_key,
    msg_data,
    agent,
    thread_id,
    reply_id,
    room_id,
    session: httpx.AsyncClient,
    workflow_bot=None,
    msg_limit=0,
):
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    json = {"input": msg_data, "sessionId": thread_id, "enableStreaming": True, "stream_token" : True}
    prev_data = ''
    prev_event = None
    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, headers=headers, json=json) as response:
            response.raise_for_status()
            async for line in response.content:
                data = line.decode('utf-8')
                # Split the line into event and data parts
                if data.startswith("name:"):
                    event = data.split("name:")[1]
                    if prev_event != event:
                        prev_event = event
                        await send_agent_message(agent[prev_event], thread_id, reply_id, prev_data, room_id, workflow_bot, msg_limit)
                        prev_data = ''
                else:
                    prev_data += line

    # Print the complete message for the last event
    if prev_event is not None:
        logging.info(f'Event: {prev_event}, Data: {prev_data}')
        await send_agent_message(agent[prev_event], thread_id, reply_id, prev_data, room_id, workflow_bot, msg_limit)
    else:
        logging.info('Failed to fetch streaming data')


async def send_agent_message(agent, thread_event_id, reply_id, data, room_id, workflow_bot=None, msg_limit=0):
    thread = {
        'rel_type': 'm.thread',
        'event_id': thread_event_id,
        'is_falling_back': True,
        'm.in_reply_to': {'event_id': reply_id}
    }
    await send_message_as_tool(agent, data, room_id, reply_id, thread, workflow_bot, msg_limit)
