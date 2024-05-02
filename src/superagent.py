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
    steps = []
    if response.json()['data'].get('intermediate_steps') != None:
        steps = response.json()['data']['intermediate_steps']
    return response.json()['data']['output'], steps

async def get_agents(superagent_url: str,agent_id: str,api_key: str, session: httpx.AsyncClient):
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
                result[tools['tool']['name']] = tool_agent_id['agentId']
    return result

async def get_tools(superagent_url: str,agent_id: str,api_key: str, session: httpx.AsyncClient):
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
    result = []
    if response.status_code == 200:
        data = response.json()['data']['tools']
        for tools in data:
            if tools['tool']['type'] == "AGENT":
                result.append(tools['agentId'])
    return result

async def create_workflow(superagent_url: str,api_key: str,session: httpx.AsyncClient):
    api_url = f"{superagent_url}/api/v1/workflows"
    headers = {
            'Authorization': f'Bearer {api_key}',
        }
    data = {
        "name" : "My Workflow",
        "description" : "desc"
    }
    response = await session.post(
            api_url,
            headers=headers,
            timeout= 30,
            data=data
    )
    if response.status_code == 200:
        data = response.json()['data']['id']
        return data
    return "error"

async def update_yaml(superagent_url: str,api_key: str,workflow_id: str, yaml: str,session: httpx.AsyncClient):
    api_url = f"{superagent_url}/api/v1/workflows/{workflow_id}/config"
    headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/x-yaml'
        }
    response = await session.post(
            api_url,
            headers=headers,
            timeout= 30,
            data=yaml
    )
    if response.status_code == 200:
        return True
    return False

async def api_key(username: str ,session: httpx.AsyncClient):
    api_url = f"https://bots.pixx.co/user/{username}"
    response = await session.get(
            api_url,
            timeout= 30
    )
    if response.status_code == 200:
        return response.content
    return ""


async def deploy_bot(email,api_key,workflow_id,session: httpx.AsyncClient):
    api_url = f"https://bots.pixx.co/add"
    data = {
        "email_id" : email,
        "bot_username" : "",
        "api_key" : api_key,
        "name" : "test workflow",
        "description" : "yaml test",
        "id" : workflow_id,
        "tags" : "",
        "publish" : False,
        "type": "WORKFLOW"
    }
    response = await session.post(
            api_url,
            timeout= 30,
            json=data
    )
    if response.status_code == 200:
        return response.content
    return ""





async def test(api_key):
    async with httpx.AsyncClient() as session:
        api_url = "https://api.pixx.co/api/v1/agents/98ab633b-c9c0-45ad-ab7e-881e8d9233a7/invoke"
        prompt = "2+2"
        headers = {
            'Authorization': f'Bearer {api_key}',
        }
        response = await superagent_invoke(api_url, prompt, session,headers=headers)
        print(response)


if __name__ == "__main__":
    import asyncio

    asyncio.run(test())
