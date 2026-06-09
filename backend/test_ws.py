import asyncio
import websockets


async def main():
    async with websockets.connect("ws://localhost:8000/ws") as ws:
        await ws.send("hi")
        reply = await ws.recv()
        print("Server replied:", reply)


asyncio.run(main())