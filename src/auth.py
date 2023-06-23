from datetime import datetime, timedelta
import pytz
from dateutil.parser import isoparse
import requests


class Auth:
    def __init__(self, access_token_url, bt):
        self._access_token_url = access_token_url
        self._bt = bt
        self._idata = None
        self._regen()

    def _regen(self):
        headers = {
            "Authorization": f"Bearer {self._bt()}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.post(self._access_token_url, data=b"", headers=headers)
        self._idata = response.json()
        print("new expires_at idata:", repr(self._idata))
        self._expires = isoparse(self._idata["expires_at"]) - timedelta(seconds=10)

    @property
    def header(self):
        now = datetime.now(pytz.UTC)
        if self._expires < now:
            print("Expired header, regenerate, (expires, now)", self._expires, now)
            self._regen()
        return {
            "Authorization": f"token {self._idata['token']}",
            "Accept": "application/vnd.github.v3+json",
        }
