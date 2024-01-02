import json
import httpx


async def superagent_invoke(
    superagent_url: str,agent_id: str, prompt: str, api_key:str, session: httpx.AsyncClient, sessionId: str=None,headers: dict = None
) -> str:
    """
    Sends a query to the Superagent API and returns the response.

    Args:
        api_url (str): The URL of the superagent API.
        prompt (str): The question to ask the API.
        session (aiohttp.ClientSession): The aiohttp session to use.
        sessionId (str) : Matrix Room id to manage sessions.
        headers (dict, optional): The headers to use. Defaults to None.

    Returns:
        str: The response from the API.
    """
    headers = {
            'Authorization': f'Bearer {api_key}',
        }
    api_url = f"{superagent_url}/api/v1/agents/{agent_id}/invoke"
    response = await session.post(
            api_url,
            json={"input": prompt, "sessionId": sessionId , "enableStreaming": False},
            headers=headers,
            timeout= 30,
        )
    return response.json()['data']['output'],response.json()['data']['intermediate_steps']

async def get_agents(superagent_url: str,agent_id: str,api_key: str, session: httpx.AsyncClient, room_id: str):
    api_url = f"{superagent_url}/api/v1/agents/{agent_id}"
    headers = {
            'Authorization': f'Bearer {api_key}',
        }
    response = await session.get(
            api_url,
            headers=headers,
            timeout= 30,
    )
    response.content
    result = {}
    if response.status_code == 200:
        data = response.json()['data']['tools']
        for tools in data:
            if tools['tool']['type'] == "AGENT":
                tool_agent_id = json.loads(tools['tool']['metadata'])
                result[tools['tool']['name']] = tool_agent_id['agent_id']
    return result





async def test(api_key):
    async with httpx.AsyncClient() as session:
        api_url = "https://api.agispace.co/api/v1/agents/98ab633b-c9c0-45ad-ab7e-881e8d9233a7/invoke"
        prompt = "2+2"
        headers = {
            'Authorization': f'Bearer {api_key}',
        }
        response = await superagent_invoke(api_url, prompt, session,headers=headers)
        print(response)


if __name__ == "__main__":
    import asyncio

    asyncio.run(test())
