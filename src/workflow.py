import json
import httpx

async def workflow_invoke(
    superagent_url: str,workflow_id: str, prompt: str, api_key:str, session: httpx.AsyncClient, sessionId: str=None,headers: dict = None
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
    api_url = f"{superagent_url}/api/v1/workflows/{workflow_id}/invoke"
    response = await session.post(
            api_url,
            json={"input": prompt, "sessionId": sessionId , "enableStreaming": False},
            headers=headers,
            timeout= 30,
        )
    result = {}
    if response.status_code == 200:
        data  = response.json()['data']
        for i in enumerate(data['steps']):
            result[i[0]] = i[1]['output']
        return result
    return {}

async def workflow_steps(superagent_url: str ,workflow_id: str, api_key: str, session: httpx.AsyncClient):
    headers = {
        'Authorization': f'Bearer {api_key}',
    }
    api_url = f"{superagent_url}/api/v1/workflows/{workflow_id}/steps"
    response = await session.get(
            api_url,
            headers=headers,
            timeout= 30,
        )
    if response.status_code == 200:
        return response.json()["data"]
    return response.json() 