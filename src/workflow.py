import httpx
import aiohttp

from api import send_message_as_tool


async def workflow_steps(superagent_url: str, workflow_id: str, api_key: str, session: httpx.AsyncClient):
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


async def stream_json_response_with_auth(api_url, api_key, msg_data, agent, thread_id, reply_id, room_id, session: httpx.AsyncClient):
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    json = {"input": msg_data, "sessionId": thread_id, "enableStreaming": True}
    prev_data = ''
    prev_event = None
    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, headers=headers, json=json) as response:
            response.raise_for_status()
            async for line in response.content:
                   # Split the line into event and data parts
                if line.startswith(b'id:'):
                    event = line.decode('utf-8').split(':', 1)[1].strip()
                    if prev_event is not None and event != prev_event:
                        # Print the complete message for the previous event
                        prev_data = prev_data.replace("````","`\n```")
                        prev_data = prev_data.replace("```", "\n```")
                        print(
                            f'Event: {prev_event}, Data: {prev_data}')
                        await send_agent_message(agent[prev_event], thread_id, reply_id, prev_data, room_id)
                        # Reset the previous data
                        prev_data = ''
                    # Get the next line which contains data
                if line.startswith(b'data:'):
                    event_data = line[6:-1]
                    if event_data == b'':
                        prev_data  += '\n'
                    elif event_data.isspace():
                        prev_data += '\n' + event_data.decode('utf-8')[1:]
                    else:
                        prev_data += event_data.decode('utf-8')

                    # Update the previous event
                    prev_event = event

    # Print the complete message for the last event
    if prev_event is not None:
        print(f'Event: {prev_event}, Data: {prev_data}')
        await send_agent_message(agent[prev_event], thread_id, reply_id, prev_data, room_id)
    else:
        print('Failed to fetch streaming data')


async def send_agent_message(agent, thread_event_id, reply_id, data, room_id):
    thread = {
        'rel_type': 'm.thread',
        'event_id': thread_event_id,
        'is_falling_back': True,
        'm.in_reply_to': {'event_id': reply_id}
    }
    await send_message_as_tool(agent, data, room_id, reply_id, thread)
