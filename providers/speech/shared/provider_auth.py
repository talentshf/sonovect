"""Protect mutating coordinator calls before body parsing on shared networks."""
import hmac
from starlette.responses import JSONResponse


class ServiceAuth:
    def __init__(self,app,token):self.app,self.token=app,token.encode()
    async def __call__(self,scope,receive,send):
        if self.token and scope['type']=='http' and scope['method'] not in {'GET','HEAD','OPTIONS'}:
            values=[value for key,value in scope['headers'] if key.lower()==b'authorization']
            scheme,_,credential=values[0].partition(b' ') if len(values)==1 else (b'',b'',b'')
            if scheme.lower()!=b'bearer' or not hmac.compare_digest(credential,self.token):
                response=JSONResponse({'detail':'authentication_required'},status_code=401,headers={'WWW-Authenticate':'Bearer'})
                return await response(scope,receive,send)
        return await self.app(scope,receive,send)
