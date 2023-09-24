import httpx


async def superagent_invoke(
    api_url: str, prompt: str, session: httpx.AsyncClient, sessionId: str=None,headers: dict = None
) -> str:
    """
    Sends a query to the Flowise API and returns the response.

    Args:
        api_url (str): The URL of the Flowise API.
        prompt (str): The question to ask the API.
        session (aiohttp.ClientSession): The aiohttp session to use.
        sessionId (str) : Matrix Room id to manage sessions.
        headers (dict, optional): The headers to use. Defaults to None.

    Returns:
        str: The response from the API.
    """
    if headers:
        response = await session.post(
            api_url,
            json={"input": prompt, "sessionId": sessionId , "enableStreaming": False},
            headers=headers,
            timeout= 30,
        )
    else:
        response = await session.post(api_url, json={"input": prompt, "sessionId": sessionId , "streaming": False})
    return response.json()


async def test():
    async with httpx.AsyncClient() as session:
        api_url = "http://localhost:8000/api/v1/agents/009252b2-6a7d-4d6f-9777-136b3dae790e/invoke"
        prompt = "2+2"
        headers = {
            'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcGlfdXNlcl9pZCI6ImU2YTg1ZjllLThmMTUtNDMyYy05ZTkxLTZhODEzZDUwZGVlZCJ9.TsdWCBE0ll0RcqZ6V9qlT19SqyrjUIgYKOKg-gVwYdY',
        }
        response = await superagent_invoke(api_url, prompt, session,headers=headers)
        print(response['data']['output'])


if __name__ == "__main__":
    import asyncio

    asyncio.run(test())
