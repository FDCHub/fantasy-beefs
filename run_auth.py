import json
import time
import webbrowser
from rauth import OAuth1Service

with open('secrets/yahoo_oauth.json') as f:
    creds = json.load(f)

service = OAuth1Service(
    consumer_key=creds['consumer_key'],
    consumer_secret=creds['consumer_secret'],
    request_token_url='https://api.login.yahoo.com/oauth/v2/get_request_token',
    access_token_url='https://api.login.yahoo.com/oauth/v2/get_access_token',
    authorize_url='https://api.login.yahoo.com/oauth/v2/request_auth',
    base_url='https://fantasysports.yahooapis.com/'
)

rt, rt_secret = service.get_request_token(params={'oauth_callback': 'oob'})
auth_url = service.get_authorize_url(rt)

print('Opening browser for Yahoo authorization...')
webbrowser.open(auth_url)
print(f'\nIf the browser did not open, visit:\n{auth_url}\n')

verifier = input('Paste the verifier code here: ').strip()
session = service.get_auth_session(rt, rt_secret, params={'oauth_verifier': verifier})

creds.update({
    'access_token': session.access_token,
    'access_token_secret': session.access_token_secret,
    'token_time': time.time(),
})
with open('secrets/yahoo_oauth.json', 'w') as f:
    json.dump(creds, f, indent=4)

print('Authorization complete — token saved to secrets/yahoo_oauth.json')
