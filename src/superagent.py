import httpx


async def superagent_invoke(
    api_url: str, prompt: str, api_key:str, session: httpx.AsyncClient, sessionId: str=None,headers: dict = None
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
    if headers:
        response = await session.post(
            api_url,
            json={"input": prompt, "sessionId": sessionId , "enableStreaming": False},
            headers=headers,
            timeout= 30,
        )
    else:
        response = await session.post(api_url, json={"input": prompt, "sessionId": sessionId , "streaming": False})
    return response.json()['data']['output'],response.json()['data']['intermediate_steps']


async def test():
    async with httpx.AsyncClient() as session:
        api_url = "https://api.immagine.ai/api/v1/agents/98ab633b-c9c0-45ad-ab7e-881e8d9233a7/invoke"
        prompt = "2+2"
        headers = {
            'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcGlfdXNlcl9pZCI6ImZkNDYwOTkzLWQ5MTgtNDE0OC05MzNkLTk2MjBlODQ2OTQ1YyJ9._wnmN64xsJb1k6ZbLnlBaQ4SmnJXit9OaEpQG4I_JyI',
        }
        response = await superagent_invoke(api_url, prompt, session,headers=headers)
        print(response)


if __name__ == "__main__":
    import asyncio

    asyncio.run(test())
