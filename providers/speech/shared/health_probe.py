"""Read-only provider discovery with one total deadline and a response cap."""
import asyncio
import json
import httpx


async def probe(url, timeout=4):
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
                async with client.stream('GET', url + '/health') as response:
                    if response.status_code != 200:
                        return {'reachable': False, 'error': 'provider_http_error'}
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 65536:
                            return {'reachable': False, 'error': 'provider_invalid_response'}
        value = json.loads(content)
        if not isinstance(value, dict):
            return {'reachable': False, 'error': 'provider_invalid_response'}
        return {'reachable': True, 'payload': value}
    except (TimeoutError, httpx.TimeoutException):
        return {'reachable': False, 'error': 'provider_timeout'}
    except httpx.HTTPError:
        return {'reachable': False, 'error': 'provider_unreachable'}
    except (ValueError, UnicodeError):
        return {'reachable': False, 'error': 'provider_invalid_response'}
