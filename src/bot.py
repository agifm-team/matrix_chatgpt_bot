import asyncio
import re
import sqlite3
import sys
import time
import traceback
from typing import Union, Optional
import urllib.parse

import httpx

from nio import (
    AsyncClient,
    AsyncClientConfig,
    InviteMemberEvent,
    JoinError,
    KeyVerificationCancel,
    KeyVerificationEvent,
    EncryptionError,
    KeyVerificationKey,
    KeyVerificationMac,
    KeyVerificationStart,
    LocalProtocolError,
    LoginResponse,
    MatrixRoom,
    MegolmEvent,
    RoomMessageText,
    ToDeviceError
)
from nio.store.database import SqliteStore
from nio.responses import ProfileGetDisplayNameError
from api import enable_api, intro_message, invite_bot_to_room, send_message_as_tool

from log import getlogger
from send_message import send_room_message, send_text_message
from superagent import get_agents, get_tools, superagent_invoke
from workflow import stream_workflow, workflow_invoke, workflow_steps

logger = getlogger()
GENERAL_ERROR_MESSAGE = "Something went wrong, please try again or contact admin."
INVALID_NUMBER_OF_PARAMETERS_MESSAGE = "Invalid number of parameters"


class DefaultDict(dict):
    def __missing__(self, key):
        return 0


class Bot:
    def __init__(
        self,
        homeserver: str,
        user_id: str,
        superagent_url: str,
        id: str,
        api_key: str,
        owner_id: str,
        type: str,
        streaming: bool,
        password: Union[str, None] = None,
        device_id: str = "MatrixChatGPTBot",
        import_keys_path: Optional[str] = None,
        import_keys_password: Optional[str] = None,
        timeout: Union[float, None] = None,
    ):
        if homeserver is None or user_id is None or device_id is None:
            logger.warning("homeserver && user_id && device_id is required")
            sys.exit(1)

        if password is None:
            logger.warning("password is required")
            sys.exit(1)
        self.scheduler = True
        self.msg_limit = DefaultDict()
        self.bot_db = sqlite3.connect("/app/keys/bot.db")
        create_table = '''CREATE TABLE IF NOT EXISTS bot
         (userId TEXT  PRIMARY KEY     NOT NULL,
         email            TEXT     NOT NULL
        );
         '''
        self.bot_db.execute(create_table)

        self.workflow = False
        self.streaming = streaming

        if type == "WORKFLOW":
            self.workflow = True
            self.workflow_id = id
        else:
            self.agent_id = id

        self.homeserver: str = homeserver
        self.user_id: str = user_id
        self.password: str = password
        self.device_id: str = device_id
        self.owner_id: str = owner_id
        self.bot_username = urllib.parse.quote(user_id)
        self.bot_username_without_homeserver = self.user_id.replace(
            ":spaceship.im", '')

        self.superagent_url = superagent_url
        self.api_key = api_key

        self.import_keys_path: str = import_keys_path
        self.import_keys_password: str = import_keys_password

        self.timeout: float = timeout or 120.0
        self.time_loop = 0
        self.last_message = time.time()

        self.base_path = "/app/keys"

        self.httpx_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.timeout,
        )

        # initialize AsyncClient object
        self.store_path = self.base_path
        self.config = AsyncClientConfig(
            store=SqliteStore,
            store_name="project",
            store_sync_tokens=True,
            encryption_enabled=True,
        )
        self.client = AsyncClient(
            homeserver=self.homeserver,
            user=self.user_id,
            device_id=self.device_id,
            config=self.config,
            store_path=self.store_path,
        )

        # setup event callbacks
        self.client.add_event_callback(
            self.message_callback, (RoomMessageText,))
        self.client.add_event_callback(self.decryption_failure, (MegolmEvent,))
        self.client.add_event_callback(
            self.invite_callback, (InviteMemberEvent,))
        self.client.add_to_device_callback(
            self.to_device_callback, (KeyVerificationEvent,)
        )

        # regular expression to match keyword commands
        self.help_prog = re.compile(r"^\s*!help\s*.*$")
        self.enable_prog = re.compile(r"\s*!enable\s+(.+)$")

    async def close(self, task: asyncio.Task) -> None:
        await self.httpx_client.aclose()
        await self.client.close()
        self.scheduler = False
        task.cancel()
        logger.info("Bot closed!")

    async def periodic_task(self):
        # while self.scheduler:
        #     await asyncio.sleep(interval)
        idle_time = time.time() - self.last_message
        if self.time_loop == 4:
            if idle_time >= 86400:
                await self.httpx_client.aclose()
                await self.client.close()
                self.scheduler = False
            else:
                self.time_loop == 0
        else:
            self.time_loop += 1
            self.msg_limit = DefaultDict()

    async def allow_message(self, sender_id):
        check_user = self.bot_db.execute(
            f"SELECT email FROM bot WHERE userId='{sender_id}'").fetchone()
        logger.info(f"check_user: {check_user}")
        if check_user:
            return True, check_user[0]
        if self.msg_limit[sender_id] <= 10:
            return True, None
        return False, None

    # message_callback RoomMessageText event

    async def message_callback(self, room: MatrixRoom, event: RoomMessageText) -> None:
        room_id = room.room_id

        # reply event_id
        reply_to_event_id = event.event_id

        # sender_id
        sender_id = event.sender

        thread_id = None
        # user_message
        raw_user_message = event.body

        body = event.source
        if room.user_name(self.user_id) is not None:
            bot_user = "@" + room.user_name(self.user_id)
        else:
            bot_user_data = await self.client.get_displayname()
            if bot_user_data == ProfileGetDisplayNameError:
                bot_user = "@1\a\a"
            else:
                bot_user = bot_user_data.displayname

        if "m.relates_to" in body["content"]:
            if body["content"]["m.relates_to"].get("rel_type") == "m.thread":
                thread_id = body["content"]["m.relates_to"]["event_id"]
                thread_event_id = thread_id
        if thread_id == None:
            thread_event_id = reply_to_event_id
        # print info to console
        logger.info(
            f"Message received in room {room.display_name}\n"
            f"{room.user_name(event.sender)} | {raw_user_message}"
        )
        tagged = False

        if bot_user in raw_user_message:
            tagged = True
        allow_message = await self.allow_message(sender_id)

        dm_tag = room.member_count == 2
        # prevent command trigger loop
        if self.user_id != event.sender and (tagged or dm_tag):
            content_body = re.sub("\r\n|\r|\n", " ", raw_user_message)
            enable_command = self.enable_prog.match(content_body)
            if enable_command:
                api_req = await enable_api(self.bot_db, sender_id, self.httpx_client)
                if api_req:
                    await send_room_message(
                        self.client,
                        room_id,
                        reply_message="api enabled successfully",
                        sender_id=sender_id,
                        user_message=raw_user_message,
                        reply_to_event_id=reply_to_event_id,
                        thread_id=thread_id,
                        msg_limit=self.msg_limit[sender_id],
                    )
                return
            if self.owner_id != sender_id and not allow_message[0]:
                await send_room_message(
                    self.client,
                    room_id,
                    reply_message=f"10 Messages Limit Exceeded!.Send !enable {self.bot_username} to use your api key set in superagent.",
                    sender_id=sender_id,
                    user_message=raw_user_message,
                    thread_id=thread_id,
                    reply_to_event_id=reply_to_event_id,
                    msg_limit=self.msg_limit[sender_id],
                )
                return
            try:
                await self.client.room_typing(room_id, typing_state=True)
                userEmail = allow_message[1]
                if self.workflow:
                    api_url = f"{self.superagent_url}/api/v1/workflows/{self.workflow_id}/invoke"
                    get_steps = await workflow_steps(self.superagent_url, self.workflow_id, self.api_key, self.httpx_client)
                    self.msg_limit[sender_id] += len(get_steps)
                    await stream_workflow(api_url, self.api_key, content_body, get_steps, thread_event_id, reply_to_event_id, room_id, self.httpx_client, self.user_id, userEmail, self.msg_limit[sender_id], single_bot=not self.streaming)
                    return

                result = await superagent_invoke(self.superagent_url, self.agent_id, content_body, self.api_key, self.httpx_client, thread_event_id)
                self.msg_limit[sender_id] += 1
                await send_room_message(
                    self.client,
                    room_id,
                    reply_message=result[0],
                    sender_id=sender_id,
                    user_message=raw_user_message,
                    reply_to_event_id=reply_to_event_id,
                    thread_id=thread_id,
                    msg_limit=self.msg_limit[sender_id],
                )
            except Exception as e:
                await self.client.room_typing(room_id, typing_state=False)
                logger.error(e)

    # message_callback decryption_failure event

    async def decryption_failure(self, room: MatrixRoom, event: MegolmEvent) -> None:
        if not isinstance(event, MegolmEvent):
            return

        logger.error(
            f"Failed to decrypt message: {event.event_id} \
                from {event.sender} in {room.room_id}\n"
            + "Please make sure the bot current session is verified"
        )

    # invite_callback event
    async def invite_callback(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        """Handle an incoming invite event.
        If an invite is received, then join the room specified in the invite.
        code copied from: https://github.com/8go/matrix-eno-bot/blob/ad037e02bd2960941109e9526c1033dd157bb212/callbacks.py#L104
        """
        logger.debug(f"Got invite to {room.room_id} from {event.sender}.")
        # Attempt to join 3 times before giving up
        for attempt in range(3):
            result = await self.client.join(room.room_id)
            if self.workflow and self.streaming:
                get_steps = await workflow_steps(self.superagent_url, self.workflow_id, self.api_key, self.httpx_client)
                for i in get_steps.values():
                    bot_username = await invite_bot_to_room(i, self.httpx_client)
                    await self.client.room_invite(room.room_id, bot_username)
            else:
                get_tools_agent_id = await get_tools(self.superagent_url, self.agent_id, self.api_key, self.httpx_client)
                if get_tools_agent_id != []:
                    for i in get_tools_agent_id:
                        bot_username = await invite_bot_to_room(i, self.httpx_client)
                        await self.client.room_invite(room.room_id, bot_username)
            if type(result) == JoinError:
                logger.error(
                    f"Error joining room {room.room_id} (attempt %d): %s",
                    attempt,
                    result.message,
                )
            else:
                break
        else:
            logger.error("Unable to join room: %s", room.room_id)

        # Successfully joined room
        logger.info(f"Joined {room.room_id}")
        if not self.workflow:
            intro = await intro_message(self.agent_id, self.httpx_client)
            logger.info(f"intro: {intro}")
            if intro:
                await send_text_message(
                    self.client,
                    room_id=room.room_id,
                    message=intro,
                )

    # to_device_callback event
    async def to_device_callback(self, event: KeyVerificationEvent) -> None:
        """Handle events sent to device.

        Specifically this will perform Emoji verification.
        It will accept an incoming Emoji verification requests
        and follow the verification protocol.
        code copied from: https://github.com/8go/matrix-eno-bot/blob/ad037e02bd2960941109e9526c1033dd157bb212/callbacks.py#L127
        """
        try:
            client = self.client
            logger.debug(
                f"Device Event of type {type(event)} received in " "to_device_cb()."
            )

            if isinstance(event, KeyVerificationStart):  # first step
                """first step: receive KeyVerificationStart
                KeyVerificationStart(
                    source={'content':
                            {'method': 'm.sas.v1',
                             'from_device': 'DEVICEIDXY',
                             'key_agreement_protocols':
                                ['curve25519-hkdf-sha256', 'curve25519'],
                             'hashes': ['sha256'],
                             'message_authentication_codes':
                                ['hkdf-hmac-sha256', 'hmac-sha256'],
                             'short_authentication_string':
                                ['decimal', 'emoji'],
                             'transaction_id': 'SomeTxId'
                             },
                            'type': 'm.key.verification.start',
                            'sender': '@user2:example.org'
                            },
                    sender='@user2:example.org',
                    transaction_id='SomeTxId',
                    from_device='DEVICEIDXY',
                    method='m.sas.v1',
                    key_agreement_protocols=[
                        'curve25519-hkdf-sha256', 'curve25519'],
                    hashes=['sha256'],
                    message_authentication_codes=[
                        'hkdf-hmac-sha256', 'hmac-sha256'],
                    short_authentication_string=['decimal', 'emoji'])
                """

                if "emoji" not in event.short_authentication_string:
                    estr = (
                        "Other device does not support emoji verification "
                        f"{event.short_authentication_string}. Aborting."
                    )
                    logger.info(estr)
                    return
                resp = await client.accept_key_verification(event.transaction_id)
                if isinstance(resp, ToDeviceError):
                    estr = f"accept_key_verification() failed with {resp}"
                    logger.info(estr)

                sas = client.key_verifications[event.transaction_id]

                todevice_msg = sas.share_key()
                resp = await client.to_device(todevice_msg)
                if isinstance(resp, ToDeviceError):
                    estr = f"to_device() failed with {resp}"
                    logger.info(estr)

            elif isinstance(event, KeyVerificationCancel):  # anytime
                """at any time: receive KeyVerificationCancel
                KeyVerificationCancel(source={
                    'content': {'code': 'm.mismatched_sas',
                                'reason': 'Mismatched authentication string',
                                'transaction_id': 'SomeTxId'},
                    'type': 'm.key.verification.cancel',
                    'sender': '@user2:example.org'},
                    sender='@user2:example.org',
                    transaction_id='SomeTxId',
                    code='m.mismatched_sas',
                    reason='Mismatched short authentication string')
                """

                # There is no need to issue a
                # client.cancel_key_verification(tx_id, reject=False)
                # here. The SAS flow is already cancelled.
                # We only need to inform the user.
                estr = (
                    f"Verification has been cancelled by {event.sender} "
                    f'for reason "{event.reason}".'
                )
                logger.info(estr)

            elif isinstance(event, KeyVerificationKey):  # second step
                """Second step is to receive KeyVerificationKey
                KeyVerificationKey(
                    source={'content': {
                            'key': 'SomeCryptoKey',
                            'transaction_id': 'SomeTxId'},
                        'type': 'm.key.verification.key',
                        'sender': '@user2:example.org'
                    },
                    sender='@user2:example.org',
                    transaction_id='SomeTxId',
                    key='SomeCryptoKey')
                """
                sas = client.key_verifications[event.transaction_id]

                logger.info(f"{sas.get_emoji()}")
                # don't log the emojis

                # The bot process must run in forground with a screen and
                # keyboard so that user can accept/reject via keyboard.
                # For emoji verification bot must not run as service or
                # in background.
                # yn = input("Do the emojis match? (Y/N) (C for Cancel) ")
                # automatic match, so we use y
                yn = "y"
                if yn.lower() == "y":
                    estr = (
                        "Match! The verification for this " "device will be accepted."
                    )
                    logger.info(estr)
                    resp = await client.confirm_short_auth_string(event.transaction_id)
                    if isinstance(resp, ToDeviceError):
                        estr = "confirm_short_auth_string() " f"failed with {resp}"
                        logger.info(estr)
                elif yn.lower() == "n":  # no, don't match, reject
                    estr = (
                        "No match! Device will NOT be verified "
                        "by rejecting verification."
                    )
                    logger.info(estr)
                    resp = await client.cancel_key_verification(
                        event.transaction_id, reject=True
                    )
                    if isinstance(resp, ToDeviceError):
                        estr = f"cancel_key_verification failed with {resp}"
                        logger.info(estr)
                else:  # C or anything for cancel
                    estr = "Cancelled by user! Verification will be " "cancelled."
                    logger.info(estr)
                    resp = await client.cancel_key_verification(
                        event.transaction_id, reject=False
                    )
                    if isinstance(resp, ToDeviceError):
                        estr = f"cancel_key_verification failed with {resp}"
                        logger.info(estr)

            elif isinstance(event, KeyVerificationMac):  # third step
                """Third step is to receive KeyVerificationMac
                KeyVerificationMac(
                    source={'content': {
                        'mac': {'ed25519:DEVICEIDXY': 'SomeKey1',
                                'ed25519:SomeKey2': 'SomeKey3'},
                        'keys': 'SomeCryptoKey4',
                        'transaction_id': 'SomeTxId'},
                        'type': 'm.key.verification.mac',
                        'sender': '@user2:example.org'},
                    sender='@user2:example.org',
                    transaction_id='SomeTxId',
                    mac={'ed25519:DEVICEIDXY': 'SomeKey1',
                         'ed25519:SomeKey2': 'SomeKey3'},
                    keys='SomeCryptoKey4')
                """
                sas = client.key_verifications[event.transaction_id]
                try:
                    todevice_msg = sas.get_mac()
                except LocalProtocolError as e:
                    # e.g. it might have been cancelled by ourselves
                    estr = (
                        f"Cancelled or protocol error: Reason: {e}.\n"
                        f"Verification with {event.sender} not concluded. "
                        "Try again?"
                    )
                    logger.info(estr)
                else:
                    resp = await client.to_device(todevice_msg)
                    if isinstance(resp, ToDeviceError):
                        estr = f"to_device failed with {resp}"
                        logger.info(estr)
                    estr = (
                        f"sas.we_started_it = {sas.we_started_it}\n"
                        f"sas.sas_accepted = {sas.sas_accepted}\n"
                        f"sas.canceled = {sas.canceled}\n"
                        f"sas.timed_out = {sas.timed_out}\n"
                        f"sas.verified = {sas.verified}\n"
                        f"sas.verified_devices = {sas.verified_devices}\n"
                    )
                    logger.info(estr)
                    estr = (
                        "Emoji verification was successful!\n"
                        "Initiate another Emoji verification from "
                        "another device or room if desired. "
                        "Or if done verifying, hit Control-C to stop the "
                        "bot in order to restart it as a service or to "
                        "run it in the background."
                    )
                    logger.info(estr)
            else:
                estr = (
                    f"Received unexpected event type {type(event)}. "
                    f"Event is {event}. Event will be ignored."
                )
                logger.info(estr)
        except BaseException:
            estr = traceback.format_exc()
            logger.info(estr)

    # send general error message

    async def send_general_error_message(
        self, room_id, reply_to_event_id, sender_id, user_message
    ):
        await send_room_message(
            self.client,
            room_id,
            reply_message=GENERAL_ERROR_MESSAGE,
            reply_to_event_id=reply_to_event_id,
            sender_id=sender_id,
            user_message=user_message,
        )

    # send Invalid number of parameters to room
    async def send_invalid_number_of_parameters_message(
        self, room_id, reply_to_event_id, sender_id, user_message
    ):
        await send_room_message(
            self.client,
            room_id,
            reply_message=INVALID_NUMBER_OF_PARAMETERS_MESSAGE,
            reply_to_event_id=reply_to_event_id,
            sender_id=sender_id,
            user_message=user_message,
        )

    # bot login
    async def login(self) -> None:
        resp = await self.client.login(password=self.password, device_name=self.device_id)
        if not isinstance(resp, LoginResponse):
            logger.error("Login Failed")
            await self.httpx_client.aclose()
            await self.client.close()
            sys.exit(1)
        logger.info("Success login via password")

    # import keys
    async def import_keys(self):
        resp = await self.client.import_keys(
            self.import_keys_path, self.import_keys_password
        )
        if isinstance(resp, EncryptionError):
            logger.error(f"import_keys failed with {resp}")
        else:
            logger.info(
                "import_keys success, please remove import_keys configuration!!!"
            )

    # sync messages in the room
    async def sync_forever(self, timeout=30000, full_state=True) -> None:
        await self.client.sync_forever(timeout=timeout, full_state=full_state)
