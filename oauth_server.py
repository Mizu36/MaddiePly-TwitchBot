from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn
from tools import debug_print

app = FastAPI()

@app.get("/oauth")
async def oauth_callback(request: Request):
    debug_print("OauthServer", "Received OAuth callback request.")
    params = dict(request.query_params)
    
    # Show the params (this will include code/token Twitch sends back)
    return HTMLResponse(f"""
    <h1>Twitch OAuth Token Received!</h1>
    <p>Copy this and put it into your bot config:</p>
    <pre>{params}</pre>
    """)

if __name__ == "__main__":
    uvicorn.run("oauth_server:app", host="127.0.0.1", port=4343, reload=True)
