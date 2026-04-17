import logging

from fastapi import WebSocket
from fastapi import WebSocketDisconnect
from itsdangerous import URLSafeTimedSerializer
from itsdangerous import BadSignature
from itsdangerous import SignatureExpired

from pyppetdb.config import Config
from pyppetdb.ws.manager import WsManager
from pyppetdb.model.ws import WsMessage


class WSLogs:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        ws_manager: WsManager,
    ):
        self._log = log
        self._config = config
        self._ws_manager = ws_manager
        self._serializer = URLSafeTimedSerializer(
            secret_key=self._config.app.secretkey,
            salt="ws-auth",
        )

    async def endpoint(
        self,
        websocket: WebSocket,
    ):
        await websocket.accept()
        user_id = None
        subscriptions = set()
        try:
            while True:
                data = await websocket.receive_text()
                msg = WsMessage.model_validate_json(json_data=data)

                if msg.msg_type == "authenticate":
                    user_id = await self._handle_authenticate(
                        websocket, msg.msg_body.token
                    )
                    if user_id is None:
                        return
                elif user_id:
                    await self._handle_message(websocket, msg, subscriptions)
                else:
                    self._log.warning(
                        msg="WS logs received message before authentication"
                    )
                    await websocket.close(code=4003)
                    return
        except WebSocketDisconnect:
            pass
        except Exception as e:
            self._log.error(msg=f"WS logs error: {e}")
            await websocket.close(code=4003)
        finally:
            await self._cleanup_subscriptions(websocket, subscriptions)

    async def _handle_authenticate(self, websocket: WebSocket, token: str):
        try:
            token_data = self._serializer.loads(
                s=token,
                max_age=5,
            )
            user_id = token_data.get("user_id")
            self._log.info(msg=f"WS logs authenticated user: {user_id}")
            return user_id
        except (BadSignature, SignatureExpired) as e:
            self._log.error(msg=f"WS logs auth failed: {e}")
            await websocket.close(code=4003)
            return None

    async def _handle_message(
        self, websocket: WebSocket, msg: WsMessage, subscriptions: set
    ):
        if msg.msg_type == "subscribe_job_logs":
            job_run_id = msg.msg_body.id
            await self._ws_manager.subscribe(
                websocket=websocket,
                job_run_id=job_run_id,
            )
            subscriptions.add(job_run_id)
        elif msg.msg_type == "unsubscribe_job_logs":
            job_run_id = msg.msg_body.id
            await self._ws_manager.unsubscribe(
                websocket=websocket,
                job_run_id=job_run_id,
            )
            subscriptions.discard(job_run_id)

    async def _cleanup_subscriptions(self, websocket: WebSocket, subscriptions: set):
        for job_run_id in list(subscriptions):
            await self._ws_manager.unsubscribe(
                websocket=websocket,
                job_run_id=job_run_id,
            )
