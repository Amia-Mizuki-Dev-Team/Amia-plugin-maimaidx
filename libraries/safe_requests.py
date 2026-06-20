import httpx
from loguru import logger as log

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except Exception as e:
    cffi_requests = None
    HAS_CURL_CFFI = False
    log.warning(f"curl_cffi 导入失败，自动回退到 httpx: {e}")


class SafeAsyncSession:
    def __init__(self, impersonate=None, **kwargs):
        self.impersonate = impersonate
        self.kwargs = kwargs
        self.curl_session = None
        self.httpx_session = None
        
        if HAS_CURL_CFFI and cffi_requests:
            try:
                self.curl_session = cffi_requests.AsyncSession(impersonate=impersonate, **kwargs)
            except Exception as e:
                log.warning(f"实例化 curl_cffi.AsyncSession 失败 ({e})，将回退至 httpx 客户端")
                self.curl_session = None
                
        if not self.curl_session:
            clean_kwargs = kwargs.copy()
            clean_kwargs.pop("impersonate", None)
            self.httpx_session = httpx.AsyncClient(**clean_kwargs)

    async def __aenter__(self):
        if self.curl_session:
            try:
                await self.curl_session.__aenter__()
            except Exception as e:
                log.warning(f"curl_cffi.AsyncSession 进入上下文失败 ({e})，切换为 httpx")
                self.curl_session = None
                clean_kwargs = self.kwargs.copy()
                clean_kwargs.pop("impersonate", None)
                self.httpx_session = httpx.AsyncClient(**clean_kwargs)
                await self.httpx_session.__aenter__()
        else:
            await self.httpx_session.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.curl_session:
            try:
                await self.curl_session.__aexit__(exc_type, exc_val, exc_tb)
            except Exception:
                pass
        if self.httpx_session:
            await self.httpx_session.__aexit__(exc_type, exc_val, exc_tb)

    async def get(self, url, headers=None, params=None, timeout=None, **kwargs):
        kwargs.pop("impersonate", None)
        if self.curl_session:
            try:
                return await self.curl_session.get(url, headers=headers, params=params, timeout=timeout, **kwargs)
            except Exception as e:
                log.warning(f"curl_cffi AsyncSession.get 请求失败 ({e})，将回退至 httpx 重新请求")
                if not self.httpx_session:
                    clean_kwargs = self.kwargs.copy()
                    clean_kwargs.pop("impersonate", None)
                    self.httpx_session = httpx.AsyncClient(**clean_kwargs)
                    await self.httpx_session.__aenter__()
        
        return await self.httpx_session.get(url, headers=headers, params=params, timeout=timeout)

    async def post(self, url, headers=None, json=None, data=None, timeout=None, **kwargs):
        kwargs.pop("impersonate", None)
        if self.curl_session:
            try:
                return await self.curl_session.post(url, headers=headers, json=json, data=data, timeout=timeout, **kwargs)
            except Exception as e:
                log.warning(f"curl_cffi AsyncSession.post 请求失败 ({e})，将回退至 httpx 重新请求")
                if not self.httpx_session:
                    clean_kwargs = self.kwargs.copy()
                    clean_kwargs.pop("impersonate", None)
                    self.httpx_session = httpx.AsyncClient(**clean_kwargs)
                    await self.httpx_session.__aenter__()
        
        return await self.httpx_session.post(url, headers=headers, json=json, data=data, timeout=timeout)


class SafeRequests:
    @staticmethod
    def get(url, headers=None, impersonate=None, timeout=None, **kwargs):
        if HAS_CURL_CFFI and cffi_requests:
            try:
                return cffi_requests.get(url, headers=headers, impersonate=impersonate, timeout=timeout, **kwargs)
            except Exception as e:
                log.warning(f"curl_cffi.get 请求发生异常 ({e})，将回退至 httpx 同步请求")
        
        # Fallback to sync httpx
        clean_kwargs = kwargs.copy()
        clean_kwargs.pop("impersonate", None)
        with httpx.Client() as client:
            resp = client.get(url, headers=headers, timeout=timeout, **clean_kwargs)
            return resp

    @staticmethod
    def AsyncSession(impersonate=None, **kwargs):
        return SafeAsyncSession(impersonate=impersonate, **kwargs)
