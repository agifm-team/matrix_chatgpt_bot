import asyncio
import os
from pathlib import Path
import re
import sys
import traceback
from typing import Union, Optional
import aiofiles.os
import base64

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
    DownloadError,
    LoginResponse,
    MatrixRoom,
    MegolmEvent,
    RoomMessageText,
    ToDeviceError,
    WhoamiResponse,
)
from nio.store.database import SqliteStore
from nio.api import Api

from log import getlogger
from send_image import send_room_image
from send_message import send_room_message
from flowise import flowise_query
from lc_manager import LCManager
from gptbot import Chatbot
from gpt_vision import gpt_vision_query
import imagegen

logger = getlogger()
DEVICE_NAME = "MatrixChatGPTBot"
GENERAL_ERROR_MESSAGE = "Something went wrong, please try again or contact admin."
INVALID_NUMBER_OF_PARAMETERS_MESSAGE = "Invalid number of parameters"


class Bot:
    def __init__(
        self,
        homeserver: str,
        user_id: str,
        device_id: str,
        password: Union[str, None] = None,
        access_token: Union[str, None] = None,
        whitelist_room_id: Optional[list[str]] = None,
        import_keys_path: Optional[str] = None,
        import_keys_password: Optional[str] = None,
        openai_api_key: Union[str, None] = None,
        gpt_api_endpoint: Optional[str] = None,
        gpt_model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        reply_count: Optional[int] = None,
        system_prompt: Optional[str] = None,
        temperature: Union[float, None] = None,
        lc_admin: Optional[list[str]] = None,
        image_generation_endpoint: Optional[str] = None,
        image_generation_backend: Optional[str] = None,
        image_generation_size: Optional[str] = None,
        image_format: Optional[str] = None,
        sdwui_steps: Optional[int] = None,
        sdwui_sampler_name: Optional[str] = None,
        sdwui_cfg_scale: Optional[float] = None,
        gpt_vision_model: Optional[str] = None,
        gpt_vision_api_endpoint: Optional[str] = None,
        timeout: Union[float, None] = None,
        custom_help_message: Optional[str] = None,
    ):
        if homeserver is None or user_id is None or device_id is None:
            logger.error("homeserver && user_id && device_id is required")
            sys.exit(1)

        if password is None and access_token is None:
            logger.error("password is required")
            sys.exit(1)

        if image_generation_endpoint and image_generation_backend not in [
            "openai",
            "sdwui",
            "localai",
            None,
        ]:
            logger.error("image_generation_backend must be openai or sdwui or localai")
            sys.exit(1)

        if image_format not in ["jpeg", "webp", "png", None]:
            logger.error(
                "image_format should be jpeg or webp or png, leave blank for jpeg"
            )
            sys.exit(1)

        self.homeserver: str = homeserver
        self.user_id: str = user_id
        self.password: str = password
        self.access_token: str = access_token
        self.device_id: str = device_id

        self.openai_api_key: str = openai_api_key
        self.gpt_api_endpoint: str = (
            gpt_api_endpoint or "https://api.openai.com/v1/chat/completions"
        )
        self.gpt_model: str = gpt_model or "gpt-3.5-turbo"
        self.max_tokens: int = max_tokens or 4000
        self.top_p: float = top_p or 1.0
        self.temperature: float = temperature or 0.8
        self.presence_penalty: float = presence_penalty or 0.0
        self.frequency_penalty: float = frequency_penalty or 0.0
        self.reply_count: int = reply_count or 1
        self.system_prompt: str = (
            system_prompt
            or "You are ChatGPT, \
            a large language model trained by OpenAI. Respond conversationally"
        )

        self.import_keys_path: str = import_keys_path
        self.import_keys_password: str = import_keys_password
        self.image_generation_endpoint: str = image_generation_endpoint
        self.image_generation_backend: str = image_generation_backend

        self.gpt_vision_model = gpt_vision_model
        self.gpt_vision_api_endpoint = gpt_vision_api_endpoint

        if image_format:
            self.image_format: str = image_format
        else:
            self.image_format = "jpeg"

        if image_generation_size is None:
            self.image_generation_size = "512x512"
            self.image_generation_width = 512
            self.image_generation_height = 512
        else:
            self.image_generation_size = image_generation_size
            self.image_generation_width = self.image_generation_size.split("x")[0]
            self.image_generation_height = self.image_generation_size.split("x")[1]

        self.sdwui_steps = sdwui_steps
        self.sdwui_sampler_name = sdwui_sampler_name
        self.sdwui_cfg_scale = sdwui_cfg_scale

        self.timeout: float = timeout or 120.0

        self.base_path = Path(os.path.dirname(__file__)).parent

        self.whitelist_room_id = whitelist_room_id
        if whitelist_room_id is not None:
            if isinstance(whitelist_room_id, str):
                whitelist_room_id_list = list()
                for room_id in whitelist_room_id.split(","):
                    whitelist_room_id_list.append(room_id.strip())
                self.whitelist_room_id = whitelist_room_id_list

        if lc_admin is not None:
            if isinstance(lc_admin, str):
                lc_admin = list(filter(None, lc_admin.split(",")))
        self.lc_admin = lc_admin
        self.lc_cache = {}
        if self.lc_admin is not None:
            # intialize LCManager
            self.lc_manager = LCManager()

        if not os.path.exists(self.base_path / "images"):
            os.mkdir(self.base_path / "images")

        self.httpx_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.timeout,
        )

        # initialize AsyncClient object
        self.store_path = self.base_path
        self.config = AsyncClientConfig(
            store=SqliteStore,
            store_name="sync_db",
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

        # initialize Chatbot object
        self.chatbot = Chatbot(
            aclient=self.httpx_client,
            api_key=self.openai_api_key,
            api_url=self.gpt_api_endpoint,
            engine=self.gpt_model,
            timeout=self.timeout,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            presence_penalty=self.presence_penalty,
            frequency_penalty=self.frequency_penalty,
            reply_count=self.reply_count,
            system_prompt=self.system_prompt,
            temperature=self.temperature,
        )

        # setup event callbacks
        self.client.add_event_callback(self.message_callback, (RoomMessageText,))
        self.client.add_event_callback(self.decryption_failure, (MegolmEvent,))
        self.client.add_event_callback(self.invite_callback, (InviteMemberEvent,))
        self.client.add_to_device_callback(
            self.to_device_callback, (KeyVerificationEvent,)
        )

        # regular expression to search keyword commands
        self.gpt_prog = re.compile(r"\s*!gpt\s+(.+)$")
        self.chat_prog = re.compile(r"\s*!chat\s+(.+)$")
        self.pic_prog = re.compile(r"\s*!pic\s+(.+)$")
        self.lc_prog = re.compile(r"\s*!lc\s+(.+)$")
        self.lcadmin_prog = re.compile(r"\s*!lcadmin\s+(.+)$")
        self.agent_prog = re.compile(r"\s*!agent\s+(.+)$")
        self.escape_user_id = re.compile("\s*:\s*(.+)$")
        self.escape_other_user_id = re.compile(".*\\n\\n(.+)$")
        self.help_prog = re.compile(r"\s*!help\s*.*$")
        self.new_prog = re.compile(r"\s*!new\s+(.+)$")

        self.custom_help_message = custom_help_message

    async def close(self, task: asyncio.Task) -> None:
        self.chatbot.cursor.close()
        self.chatbot.conn.close()
        await self.httpx_client.aclose()
        if self.lc_admin is not None:
            self.lc_manager.c.close()
            self.lc_manager.conn.close()
        await self.client.close()
        task.cancel()
        logger.info("Bot closed!")

    # message_callback RoomMessageText event
    async def message_callback(self, room: MatrixRoom, event: RoomMessageText) -> None:
        if self.whitelist_room_id is not None:
            if room.room_id not in self.whitelist_room_id:
                return
        room_id = room.room_id

        # reply event_id
        reply_to_event_id = event.event_id

        # sender_id
        sender_id = event.sender

        # event source
        event_source = event.source

        # user_message
        raw_user_message = event.body

        # print info to console
        logger.info(
            f"Message received in room {room.display_name}\n"
            f"{room.user_name(event.sender)} | {raw_user_message}"
        )

        # prevent command trigger loop
        if self.user_id != event.sender:
            # remove newline character from event.body
            content_body = re.sub("\r\n|\r|\n", " ", raw_user_message)

            # @bot and reply in thread
            # gpt vision for element web
            if "m.mentions" in event_source["content"]:
                if "user_ids" in event_source["content"]["m.mentions"]:
                    # @bot
                    if (
                        self.user_id
                        in event_source["content"]["m.mentions"]["user_ids"]
                    ):
                        if "m.relates_to" in event.source["content"]:
                            if (
                                "m.in_reply_to"
                                in event_source["content"]["m.relates_to"]
                            ):
                                in_reply_to_event_id = event_source["content"][
                                    "m.relates_to"
                                ]["m.in_reply_to"]["event_id"]
                                event_info = await self.get_event(
                                    room_id, in_reply_to_event_id
                                )
                                msgtype = event_info["content"]["msgtype"]

                                # gpt vision, don't work in E2EE room
                                if "m.image" == msgtype:
                                    if (
                                        self.gpt_vision_api_endpoint is None
                                        or self.gpt_vision_model is None
                                    ):
                                        return
                                    v = self.escape_user_id.search(content_body)
                                    if v:
                                        prompt = v.group(1)
                                        image_mimetype = event_info["content"]["info"][
                                            "mimetype"
                                        ]
                                        url = event_info["content"]["url"]
                                        resp = await self.download_mxc(url)
                                        if isinstance(resp, DownloadError):
                                            logger.error("Download of image failed")
                                        else:
                                            b64_image = base64.b64encode(
                                                resp.body
                                            ).decode("utf-8")
                                            image_url = f"data:{image_mimetype};base64,{b64_image}"
                                            asyncio.create_task(
                                                self.gpt_vision_cmd(
                                                    room_id,
                                                    reply_to_event_id,
                                                    prompt,
                                                    image_url,
                                                    sender_id,
                                                    raw_user_message,
                                                )
                                            )
                                            return
                        # thread level chatting
                        else:
                            try:
                                asyncio.create_task(
                                    self.thread_chat(
                                        room_id,
                                        reply_to_event_id,
                                        sender_id=sender_id,
                                        thread_root_id=reply_to_event_id,
                                        prompt=content_body,
                                    )
                                )
                            except Exception as e:
                                logger.error(e)

                            return

            # gpt vision for element android
            elif "formatted_body" in event_source["content"]:
                if (
                    self.user_id in event_source["content"]["formatted_body"]
                    and "m.relates_to" in event_source["content"]
                ):
                    if "m.in_reply_to" in event_source["content"]["m.relates_to"]:
                        in_reply_to_event_id = event_source["content"]["m.relates_to"][
                            "m.in_reply_to"
                        ]["event_id"]
                        event_info = await self.get_event(room_id, in_reply_to_event_id)
                        msgtype = event_info["content"]["msgtype"]

                        # gpt vision, don't work in E2EE room
                        if "m.image" == msgtype:
                            if (
                                self.gpt_vision_api_endpoint is None
                                or self.gpt_vision_model is None
                            ):
                                return
                            v = self.escape_user_id.search(content_body)
                            if v:
                                prompt = v.group(1)
                                image_mimetype = event_info["content"]["info"][
                                    "mimetype"
                                ]
                                url = event_info["content"]["url"]
                                resp = await self.download_mxc(url)
                                if isinstance(resp, DownloadError):
                                    logger.error("Download of image failed")
                                else:
                                    b64_image = base64.b64encode(resp.body).decode(
                                        "utf-8"
                                    )
                                    image_url = (
                                        f"data:{image_mimetype};base64,{b64_image}"
                                    )
                                    if (
                                        "rel_type"
                                        in event_source["content"]["m.relates_to"]
                                    ):
                                        if (
                                            "m.thread"
                                            == event_source["content"]["m.relates_to"][
                                                "rel_type"
                                            ]
                                        ):
                                            thread_root_id = event_source["content"][
                                                "m.relates_to"
                                            ]["event_id"]
                                            asyncio.create_task(
                                                self.gpt_vision_cmd(
                                                    room_id,
                                                    reply_to_event_id,
                                                    prompt,
                                                    image_url,
                                                    sender_id,
                                                    raw_user_message,
                                                    reply_in_thread=True,
                                                    thread_root_id=thread_root_id,
                                                )
                                            )
                                            return

                                    asyncio.create_task(
                                        self.gpt_vision_cmd(
                                            room_id,
                                            reply_to_event_id,
                                            prompt,
                                            image_url,
                                            sender_id,
                                            raw_user_message,
                                        )
                                    )
                                    return

            #  element android does not have m.mentions, we use another way to make thread level chatting work
            if "formatted_body" in event_source["content"]:
                if (
                    self.user_id in event_source["content"]["formatted_body"]
                    and "m.relates_to" not in event_source["content"]
                ):
                    try:
                        asyncio.create_task(
                            self.thread_chat(
                                room_id,
                                reply_to_event_id,
                                sender_id=sender_id,
                                thread_root_id=reply_to_event_id,
                                prompt=content_body,
                            )
                        )
                    except Exception as e:
                        logger.error(e)

                    return

            # thread converstaion
            if "m.relates_to" in event_source["content"]:
                if "rel_type" in event_source["content"]["m.relates_to"]:
                    thread_root_id = event_source["content"]["m.relates_to"]["event_id"]
                    # thread is created by @bot
                    if thread_root_id in self.chatbot.conversation:
                        msgtype = event_source["content"]["msgtype"]

                        if "m.in_reply_to" in event_source["content"]["m.relates_to"]:
                            in_reply_to_event_id = event_source["content"][
                                "m.relates_to"
                            ]["m.in_reply_to"]["event_id"]
                            event_info = await self.get_event(
                                room_id, in_reply_to_event_id
                            )
                            if "msgtype" in event_info["content"]:
                                last_msgtype = event_info["content"]["msgtype"]
                                # gpt vision
                                if "m.image" == last_msgtype:
                                    if (
                                        self.gpt_vision_api_endpoint is None
                                        or self.gpt_vision_model is None
                                    ):
                                        return
                                    image_mimetype = event_info["content"]["info"][
                                        "mimetype"
                                    ]
                                    s = self.escape_other_user_id.search(
                                        event_source["content"]["body"]
                                    )
                                    if s:
                                        prompt = s.group(1)
                                        url = event_info["content"]["url"]
                                        resp = await self.download_mxc(url)
                                        if isinstance(resp, DownloadError):
                                            logger.error("Download of image failed")
                                        else:
                                            b64_image = base64.b64encode(
                                                resp.body
                                            ).decode("utf-8")
                                            image_url = f"data:{image_mimetype};base64,{b64_image}"

                                        asyncio.create_task(
                                            self.gpt_vision_cmd(
                                                room_id,
                                                reply_to_event_id,
                                                prompt,
                                                image_url,
                                                sender_id,
                                                raw_user_message,
                                                reply_in_thread=True,
                                                thread_root_id=thread_root_id,
                                            )
                                        )
                                        return

                            if "m.text" == msgtype:
                                # !pic command for thread chatting
                                p = self.pic_prog.search(content_body)
                                if p:
                                    prompt = p.group(1)
                                    try:
                                        asyncio.create_task(
                                            self.pic(
                                                room_id,
                                                prompt,
                                                reply_to_event_id,
                                                sender_id,
                                                raw_user_message,
                                                reply_in_thread=True,
                                                thread_root_id=thread_root_id,
                                            )
                                        )
                                    except Exception as e:
                                        logger.error(e)

                                    return

                                # !help command for thread chatting
                                h = self.help_prog.search(content_body)
                                if h:
                                    try:
                                        asyncio.create_task(
                                            self.help(
                                                room_id,
                                                reply_to_event_id,
                                                sender_id,
                                                raw_user_message,
                                                reply_in_thread=True,
                                                thread_root_id=thread_root_id,
                                            )
                                        )
                                    except Exception as e:
                                        logger.error(e)

                                    return

                                # normal chatting function
                                try:
                                    asyncio.create_task(
                                        self.thread_chat(
                                            room_id,
                                            reply_to_event_id,
                                            sender_id=sender_id,
                                            thread_root_id=thread_root_id,
                                            prompt=content_body,
                                        )
                                    )
                                except Exception as e:
                                    logger.error(e)

                                return

            # common command

            # !gpt command
            if (
                self.openai_api_key is not None
                or self.gpt_api_endpoint != "https://api.openai.com/v1/chat/completions"
            ):
                m = self.gpt_prog.match(content_body)
                if m:
                    prompt = m.group(1)
                    try:
                        asyncio.create_task(
                            self.thread_chat(
                                room_id,
                                reply_to_event_id,
                                thread_root_id=reply_to_event_id,
                                sender_id=sender_id,
                                prompt=prompt
                            )
                        )
                    except Exception as e:
                        logger.error(e)

                    return

            # !chat command
            if (
                self.openai_api_key is not None
                or self.gpt_api_endpoint != "https://api.openai.com/v1/chat/completions"
            ):
                n = self.chat_prog.match(content_body)
                if n:
                    prompt = n.group(1)
                    try:
                        asyncio.create_task(
                            self.thread_chat(
                                room_id,
                                reply_to_event_id,
                                thread_root_id=reply_to_event_id,
                                sender_id=sender_id,
                                prompt=prompt
                            )
                        )
                    except Exception as e:
                        logger.error(e)

                    return

            # lc command
            if self.lc_admin is not None:
                perm_flags = 0
                m = self.lc_prog.search(content_body)
                if m:
                    try:
                        # room_level permission
                        if room_id not in self.lc_cache:
                            # get info from db
                            datas = self.lc_manager.get_specific_by_username(room_id)
                            if len(datas) != 0:
                                # tuple
                                agent = self.lc_manager.get_command_agent(room_id)[0][0]
                                api_url = self.lc_manager.get_command_api_url(
                                    room_id, agent
                                )[0][0]
                                api_key = self.lc_manager.get_command_api_key(
                                    room_id, agent
                                )[0][0]
                                permission = self.lc_manager.get_command_permission(
                                    room_id, agent
                                )[0][0]
                                self.lc_cache[room_id] = {
                                    "agent": agent,
                                    "api_url": api_url,
                                    "api_key": api_key,
                                    "permission": permission,
                                }
                                perm_flags = permission
                        else:
                            # get info from cache
                            agent = self.lc_cache[room_id]["agent"]
                            api_url = self.lc_cache[room_id]["api_url"]
                            api_key = self.lc_cache[room_id]["api_key"]
                            perm_flags = self.lc_cache[room_id]["permission"]

                        if perm_flags == 0:
                            # check user_level permission
                            if sender_id not in self.lc_cache:
                                # get info from db
                                datas = self.lc_manager.get_specific_by_username(
                                    sender_id
                                )
                                if len(datas) != 0:
                                    # tuple
                                    agent = self.lc_manager.get_command_agent(
                                        sender_id
                                    )[0][0]
                                    # tuple
                                    api_url = self.lc_manager.get_command_api_url(
                                        sender_id, agent
                                    )[0][0]
                                    # tuple
                                    api_key = self.lc_manager.get_command_api_key(
                                        sender_id, agent
                                    )[0][0]
                                    # tuple
                                    permission = self.lc_manager.get_command_permission(
                                        sender_id, agent
                                    )[0][0]
                                    self.lc_cache[sender_id] = {
                                        "agent": agent,
                                        "api_url": api_url,
                                        "api_key": api_key,
                                        "permission": permission,
                                    }
                                    perm_flags = permission
                            else:
                                # get info from cache
                                agent = self.lc_cache[sender_id]["agent"]
                                api_url = self.lc_cache[sender_id]["api_url"]
                                api_key = self.lc_cache[sender_id]["api_key"]
                                perm_flags = self.lc_cache[sender_id]["permission"]
                    except Exception as e:
                        logger.error(e)

                    prompt = m.group(1)
                    try:
                        if perm_flags == 1:
                            # have privilege to use langchain
                            asyncio.create_task(
                                self.lc(
                                    room_id,
                                    reply_to_event_id,
                                    prompt,
                                    sender_id,
                                    raw_user_message,
                                    api_url,
                                    api_key,
                                )
                            )
                        else:
                            # no privilege to use langchain
                            await send_room_message(
                                self.client,
                                room_id,
                                reply_message="You don't have permission to use langchain",  # noqa: E501
                                sender_id=sender_id,
                                user_message=raw_user_message,
                                reply_to_event_id=reply_to_event_id,
                            )
                    except Exception as e:
                        await send_room_message(self.client, room_id, reply_message={e})
                        logger.error(e)

            # lc_admin command
            """
            username: user_id or room_id
            - user_id: @xxxxx:xxxxx.xxxxx
            - room_id: !xxxxx:xxxxx.xxxxx

            agent_name: the name of the agent
            api_url: api_endpoint
            api_key: api_key (Optional)
            permission: integer (can: 1, cannot: 0)

            {1} update api_url
            {2} update api_key
            {3} update permission
            {4} update agent name

            # add langchain endpoint
            !lcadmin add {username} {agent_name} {api_url} {api_key *Optional} {permission}

            # update api_url
            !lcadmin update {1} {username} {agent} {api_url}
            # update api_key
            !lcadmin update {2} {username} {agent} {api_key}
            # update permission
            !lcadmin update {3} {username} {agent} {permission}
            # update agent name
            !lcadmin update {4} {username} {agent} {api_url}

            # delete agent
            !lcadmin delete {username} {agent}

            # delete all agent
            !lcadmin delete {username}

            # list agent
            !lcadmin list {username}

            # list all agents
            !lcadmin list
            """  # noqa: E501
            if self.lc_admin is not None:
                q = self.lcadmin_prog.search(content_body)
                if q:
                    if sender_id in self.lc_admin:
                        try:
                            command_with_params = q.group(1).strip()
                            split_items = re.sub(
                                "\s{1,}", " ", command_with_params
                            ).split(" ")
                            command = split_items[0].strip()
                            params = split_items[1:]
                            if command == "add":
                                if not 4 <= len(params) <= 5:
                                    logger.warning("Invalid number of parameters")
                                    await self.send_invalid_number_of_parameters_message(  # noqa: E501
                                        room_id,
                                        reply_to_event_id,
                                        sender_id,
                                        raw_user_message,
                                    )
                                else:
                                    try:
                                        if len(params) == 4:
                                            (
                                                username,
                                                agent,
                                                api_url,
                                                permission,
                                            ) = params
                                            self.lc_manager.add_command(
                                                username,
                                                agent,
                                                api_url,
                                                api_key=None,
                                                permission=int(permission),
                                            )
                                            logger.info(
                                                f"\n \
                                                add {agent}:\n \
                                                username: {username}\n \
                                                api_url: {api_url}\n \
                                                permission: {permission} \
                                                "
                                            )
                                            await send_room_message(
                                                self.client,
                                                room_id,
                                                reply_message="add successfully!",
                                                sender_id=sender_id,
                                                user_message=raw_user_message,
                                                reply_to_event_id="",
                                            )
                                        elif len(params) == 5:
                                            (
                                                username,
                                                agent,
                                                api_url,
                                                api_key,
                                                permission,
                                            ) = params
                                            self.lc_manager.add_command(
                                                username,
                                                agent,
                                                api_url,
                                                api_key,
                                                int(permission),
                                            )
                                            logger.info(
                                                f"\n \
                                                        add {agent}:\n \
                                                        username: {username}\n \
                                                        api_url: {api_url}\n \
                                                        permission: {permission}\n \
                                                        api_key: {api_key} \
                                                        "
                                            )
                                            await send_room_message(
                                                self.client,
                                                room_id,
                                                reply_message="add successfully!",
                                                sender_id=sender_id,
                                                user_message=raw_user_message,
                                                reply_to_event_id="",
                                            )
                                    except Exception as e:
                                        logger.error(e)
                                        await send_room_message(
                                            self.client,
                                            room_id,
                                            reply_message=str(e),
                                        )
                            elif command == "update":
                                if not len(params) == 4:
                                    logger.warning("Invalid number of parameters")
                                    await self.send_invalid_number_of_parameters_message(  # noqa: E501
                                        room_id,
                                        reply_to_event_id,
                                        sender_id,
                                        raw_user_message,
                                    )
                                else:
                                    # {1} update api_url
                                    if params[0].strip() == "1":
                                        username, agent, api_url = params[1:]
                                        self.lc_manager.update_command_api_url(
                                            username, agent, api_url
                                        )
                                        logger.info(
                                            f"{username}-{agent}-{api_url} updated! "
                                            + str(
                                                self.lc_manager.get_specific_by_agent(
                                                    agent
                                                )
                                            ),
                                        )
                                        await send_room_message(
                                            self.client,
                                            room_id,
                                            reply_message=f"{username}-{agent}-{api_url} updated! "  # noqa: E501
                                            + str(
                                                self.lc_manager.get_specific_by_agent(
                                                    agent
                                                )
                                            ),
                                            sender_id=sender_id,
                                            user_message=raw_user_message,
                                            reply_to_event_id="",
                                        )
                                        # update cache
                                        if sender_id not in self.lc_cache:
                                            agent = agent
                                            api_url = api_url
                                            api_key = (
                                                self.lc_manager.get_command_api_key(
                                                    username, agent
                                                )[0][0]
                                            )

                                            permission = (
                                                self.lc_manager.get_command_permission(
                                                    username, agent
                                                )[0][0]
                                            )
                                            self.lc_cache[sender_id] = {
                                                "agent": agent,
                                                "api_url": api_url,
                                                "api_key": api_key,
                                                "permission": permission,
                                            }
                                        else:
                                            if (
                                                self.lc_cache[sender_id]["agent"]
                                                == agent
                                            ):
                                                self.lc_cache[sender_id][
                                                    "api_url"
                                                ] = api_url

                                    # {2} update api_key
                                    elif params[0].strip() == "2":
                                        username, agent, api_key = params[1:]
                                        self.lc_manager.update_command_api_key(
                                            username, agent, api_key
                                        )
                                        logger.info(
                                            f"{username}-{agent}-api_key updated! "
                                            + str(
                                                self.lc_manager.get_specific_by_agent(
                                                    agent
                                                )
                                            ),
                                        )
                                        await send_room_message(
                                            self.client,
                                            room_id,
                                            reply_message=f"{username}-{agent}-{api_key} updated! "  # noqa: E501
                                            + str(
                                                self.lc_manager.get_specific_by_agent(
                                                    agent
                                                )
                                            ),
                                            sender_id=sender_id,
                                            user_message=raw_user_message,
                                            reply_to_event_id="",
                                        )

                                        # update cache
                                        if sender_id not in self.lc_cache:
                                            agent = agent
                                            api_url = (
                                                self.lc_manager.get_command_api_url(
                                                    username, agent
                                                )[0][0]
                                            )
                                            api_key = api_key
                                            permission = (
                                                self.lc_manager.get_command_permission(
                                                    username, agent
                                                )[0][0]
                                            )

                                            self.lc_cache[sender_id] = {
                                                "agent": agent,
                                                "api_url": api_url,
                                                "api_key": api_key,
                                                "permission": permission,
                                            }
                                        else:
                                            if (
                                                self.lc_cache[sender_id]["agent"]
                                                == agent
                                            ):
                                                self.lc_cache[sender_id][
                                                    "api_key"
                                                ] = api_key

                                    # {3} update permission
                                    elif params[0].strip() == "3":
                                        username, agent, permission = params[1:]
                                        if permission not in ["0", "1"]:
                                            logger.warning("Invalid permission value")
                                            await send_room_message(
                                                self.client,
                                                room_id,
                                                reply_message="Invalid permission value",  # noqa: E501
                                                sender_id=sender_id,
                                                user_message=raw_user_message,
                                                reply_to_event_id="",
                                            )
                                        else:
                                            self.lc_manager.update_command_permission(
                                                username, agent, int(permission)
                                            )
                                            logger.info(
                                                f"{username}-{agent}-permission updated! "  # noqa: E501
                                                + str(
                                                    self.lc_manager.get_specific_by_agent(
                                                        agent
                                                    )
                                                ),
                                            )
                                            await send_room_message(
                                                self.client,
                                                room_id,
                                                reply_message=f"{username}-{agent}-permission updated! "  # noqa: E501
                                                + str(
                                                    self.lc_manager.get_specific_by_agent(
                                                        agent
                                                    )
                                                ),
                                                sender_id=sender_id,
                                                user_message=raw_user_message,
                                                reply_to_event_id="",
                                            )

                                            # update cache
                                            if sender_id not in self.lc_cache:
                                                agent = agent
                                                api_url = (
                                                    self.lc_manager.get_command_api_url(
                                                        username, agent
                                                    )[0][0]
                                                )
                                                api_key = (
                                                    self.lc_manager.get_command_api_key(
                                                        username, agent
                                                    )[0][0]
                                                )
                                                permission = permission
                                                self.lc_cache[sender_id] = {
                                                    "agent": agent,
                                                    "api_url": api_url,
                                                    "api_key": api_key,
                                                    "permission": permission,
                                                }
                                            else:
                                                if (
                                                    self.lc_cache[sender_id]["agent"]
                                                    == agent
                                                ):
                                                    self.lc_cache[sender_id][
                                                        "permission"
                                                    ] = permission

                                    # {4} update agent name
                                    elif params[0].strip() == "4":
                                        try:
                                            username, agent, api_url = params[1:]
                                            self.lc_manager.update_command_agent(
                                                username, agent, api_url
                                            )
                                            logger.info(
                                                "Agent name updated! "
                                                + str(
                                                    self.lc_manager.get_specific_by_agent(
                                                        agent
                                                    )
                                                ),
                                            )
                                            await send_room_message(
                                                self.client,
                                                room_id,
                                                reply_message="Agent name updated! "
                                                + str(
                                                    self.lc_manager.get_specific_by_agent(
                                                        agent
                                                    )
                                                ),
                                                sender_id=sender_id,
                                                user_message=raw_user_message,
                                                reply_to_event_id="",
                                            )
                                            # update cache
                                            if sender_id not in self.lc_cache:
                                                agent = agent
                                                api_url = api_url
                                                api_key = (
                                                    self.lc_manager.get_command_api_key(
                                                        username, agent
                                                    )[0][0]
                                                )
                                                permission = self.lc_manager.get_command_permission(  # noqa: E501
                                                    username, agent
                                                )[
                                                    0
                                                ][
                                                    0
                                                ]
                                                self.lc_cache[sender_id] = {
                                                    "agent": agent,
                                                    "api_url": api_url,
                                                    "api_key": api_key,
                                                    "permission": permission,
                                                }
                                            else:
                                                self.lc_cache[sender_id][
                                                    "agent"
                                                ] = agent
                                        except Exception as e:
                                            logger.error(e)
                                            await send_room_message(
                                                self.client,
                                                room_id,
                                                reply_message=str(e),
                                            )
                            elif command == "delete":
                                if not 1 <= len(params) <= 2:
                                    logger.warning("Invalid number of parameters")
                                    await self.send_invalid_number_of_parameters_message(  # noqa: E501
                                        room_id,
                                        reply_to_event_id,
                                        sender_id,
                                        raw_user_message,
                                    )
                                else:
                                    if len(params) == 1:
                                        username = params[0]
                                        self.lc_manager.delete_commands(username)
                                        logger.info(f"Delete all agents of {username}")
                                        await send_room_message(
                                            self.client,
                                            room_id,
                                            reply_message="Delete Successfully!",
                                            sender_id=sender_id,
                                            user_message=raw_user_message,
                                            reply_to_event_id="",
                                        )
                                        # remove from cache
                                        if username in self.lc_cache:
                                            del self.lc_cache[username]
                                    elif len(params) == 2:
                                        username, agent = params
                                        self.lc_manager.delete_command(username, agent)
                                        logger.info(f"Delete {agent} of {username}")
                                        await send_room_message(
                                            self.client,
                                            room_id,
                                            reply_message="Delete Successfully!",
                                            sender_id=sender_id,
                                            user_message=raw_user_message,
                                            reply_to_event_id="",
                                        )
                                        # remove cache
                                        if username in self.lc_cache:
                                            if (
                                                agent
                                                == self.lc_cache[username]["agent"]
                                            ):
                                                del self.lc_cache[username]

                            elif command == "list":
                                if not 0 <= len(params) <= 1:
                                    logger.warning("Invalid number of parameters")
                                    await self.send_invalid_number_of_parameters_message(  # noqa: E501
                                        room_id,
                                        reply_to_event_id,
                                        sender_id,
                                        raw_user_message,
                                    )
                                else:
                                    if len(params) == 0:
                                        total_info = self.lc_manager.get_all()
                                        logger.info(f"{total_info}")
                                        await send_room_message(
                                            self.client,
                                            room_id,
                                            reply_message=f"{total_info}",
                                            sender_id=sender_id,
                                            user_message=raw_user_message,
                                            reply_to_event_id="",
                                        )
                                    elif len(params) == 1:
                                        username = params[0]
                                        user_info = (
                                            self.lc_manager.get_specific_by_username(
                                                username
                                            )
                                        )
                                        logger.info(f"{user_info}")
                                        await send_room_message(
                                            self.client,
                                            room_id,
                                            reply_message=f"{user_info}",
                                            sender_id=sender_id,
                                            user_message=raw_user_message,
                                            reply_to_event_id="",
                                        )

                        except Exception as e:
                            logger.error(e)
                    # endif if sender_id in self.lc_admin
                    else:
                        logger.warning(f"{sender_id} is not admin")
                        await send_room_message(
                            self.client,
                            room_id,
                            reply_message=f"{sender_id} is not admin",
                            sender_id=sender_id,
                            user_message=raw_user_message,
                            reply_to_event_id=reply_to_event_id,
                        )

            # !agent command
            a = self.agent_prog.search(content_body)
            if a:
                command_with_params = a.group(1).strip()
                split_items = re.sub("\s{1,}", " ", command_with_params).split(" ")
                command = split_items[0].strip()
                params = split_items[1:]
                try:
                    if command == "list":
                        agents = self.lc_manager.get_command_agent(sender_id)
                        await send_room_message(
                            self.client,
                            room_id,
                            reply_message=f"{agents}",
                            sender_id=sender_id,
                            user_message=raw_user_message,
                            reply_to_event_id=reply_to_event_id,
                        )
                    elif command == "use":
                        if not len(params) == 1:
                            logger.warning("Invalid number of parameters")
                            await self.send_invalid_number_of_parameters_message(
                                room_id,
                                reply_to_event_id,
                                sender_id,
                                raw_user_message,
                            )
                        else:
                            agent = params[0]
                            if (agent,) in self.lc_manager.get_command_agent(sender_id):
                                # update cache
                                # tuple
                                api_url = self.lc_manager.get_command_api_url(
                                    sender_id, agent
                                )[0][0]
                                api_key = self.lc_manager.get_command_api_key(
                                    sender_id, agent
                                )[0][0]
                                permission = self.lc_manager.get_command_permission(
                                    sender_id, agent
                                )[0][0]
                                self.lc_cache[sender_id] = {
                                    "agent": agent,
                                    "api_url": api_url,
                                    "api_key": api_key,
                                    "permission": permission,
                                }
                                await send_room_message(
                                    self.client,
                                    room_id,
                                    reply_message=f"Use {agent} successfully!",
                                    sender_id=sender_id,
                                    user_message=raw_user_message,
                                    reply_to_event_id=reply_to_event_id,
                                )
                            else:
                                logger.warning(
                                    f"{agent} is not in {sender_id} agent list"
                                )
                                await send_room_message(
                                    self.client,
                                    room_id,
                                    reply_message=f"{agent} is not in {sender_id} agent list",  # noqa: E501
                                    sender_id=sender_id,
                                    user_message=raw_user_message,
                                    reply_to_event_id=reply_to_event_id,
                                )

                except Exception as e:
                    logger.error(e)

            # !new command
            n = self.new_prog.search(content_body)
            if n:
                new_command = n.group(1)
                try:
                    asyncio.create_task(
                        self.new(
                            room_id,
                            reply_to_event_id,
                            sender_id,
                            raw_user_message,
                            new_command,
                        )
                    )
                except Exception as e:
                    logger.error(e)

                return

            # !pic command
            p = self.pic_prog.search(content_body)
            if p:
                prompt = p.group(1)
                try:
                    asyncio.create_task(
                        self.pic(
                            room_id,
                            prompt,
                            reply_to_event_id,
                            sender_id,
                            raw_user_message,
                        )
                    )
                except Exception as e:
                    logger.error(e)

                return

            # help command
            h = self.help_prog.search(content_body)
            if h:
                try:
                    asyncio.create_task(
                        self.help(
                            room_id, reply_to_event_id, sender_id, raw_user_message
                        )
                    )
                except Exception as e:
                    logger.error(e)

                return

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

    # thread chat
    async def thread_chat(
        self, room_id, reply_to_event_id, thread_root_id, prompt, sender_id
    ):
        try:
            await self.client.room_typing(room_id, timeout=int(self.timeout) * 1000)
            content = await self.chatbot.ask_async_v2(
                prompt=prompt,
                convo_id=thread_root_id,
            )
            await send_room_message(
                self.client,
                room_id,
                reply_message=content,
                reply_to_event_id=reply_to_event_id,
                sender_id=sender_id,
                reply_in_thread=True,
                thread_root_id=thread_root_id,
            )
        except Exception as e:
            logger.error(e)
            await send_room_message(
                self.client,
                room_id,
                reply_message=GENERAL_ERROR_MESSAGE,
                sender_id=sender_id,
                reply_to_event_id=reply_to_event_id,
                reply_in_thread=True,
                thread_root_id=thread_root_id,
            )

    # !chat command
    async def chat(self, room_id, reply_to_event_id, prompt, sender_id, user_message):
        try:
            await self.client.room_typing(room_id, timeout=int(self.timeout) * 1000)
            content = await self.chatbot.ask_async_v2(
                prompt=prompt,
                convo_id=sender_id,
            )
            await send_room_message(
                self.client,
                room_id,
                reply_message=content,
                reply_to_event_id=reply_to_event_id,
                sender_id=sender_id,
                user_message=user_message,
            )
        except Exception as e:
            logger.error(e)
            await self.send_general_error_message(
                room_id, reply_to_event_id, sender_id, user_message
            )

    # !gpt command
    async def gpt(
        self, room_id, reply_to_event_id, prompt, sender_id, user_message
    ) -> None:
        try:
            # sending typing state, seconds to milliseconds
            await self.client.room_typing(room_id, timeout=int(self.timeout) * 1000)
            responseMessage = await self.chatbot.oneTimeAsk(
                prompt=prompt,
            )

            await send_room_message(
                self.client,
                room_id,
                reply_message=responseMessage.strip(),
                reply_to_event_id=reply_to_event_id,
                sender_id=sender_id,
                user_message=user_message,
            )
        except Exception as e:
            logger.error(e)
            await self.send_general_error_message(
                room_id, reply_to_event_id, sender_id, user_message
            )

    # gpt vision
    async def gpt_vision_cmd(
        self,
        room_id: str,
        reply_to_event_id: str,
        prompt: str,
        image_url: str,
        sender_id: str,
        user_message: str,
        reply_in_thread=False,
        thread_root_id=None,
    ) -> None:
        try:
            # sending typing state, seconds to milliseconds
            await self.client.room_typing(room_id, timeout=int(self.timeout) * 1000)
            responseMessage = await gpt_vision_query(
                self.gpt_vision_api_endpoint,
                prompt,
                image_url,
                self.gpt_vision_model,
                self.httpx_client,
                api_key=self.openai_api_key,
                timeout=self.timeout,
            )
            await send_room_message(
                self.client,
                room_id,
                reply_message=responseMessage.strip(),
                reply_to_event_id=reply_to_event_id,
                sender_id=sender_id,
                user_message=user_message,
                reply_in_thread=reply_in_thread,
                thread_root_id=thread_root_id,
            )
            if reply_in_thread and thread_root_id:
                # add gpt vision to thread context
                self.chatbot.add_to_conversation(
                    message=responseMessage, role="assistant", convo_id=thread_root_id
                )

        except Exception as e:
            logger.error(e)
            await self.send_general_error_message(
                room_id, reply_to_event_id, sender_id, user_message
            )

    # !lc command
    async def lc(
        self,
        room_id: str,
        reply_to_event_id: str,
        prompt: str,
        sender_id: str,
        user_message: str,
        flowise_api_url: str,
        flowise_api_key: str = None,
    ) -> None:
        try:
            # sending typing state
            await self.client.room_typing(room_id, timeout=int(self.timeout) * 1000)
            if flowise_api_key is not None:
                headers = {"Authorization": f"Bearer {flowise_api_key}"}
                responseMessage = await flowise_query(
                    flowise_api_url, prompt, self.httpx_client, headers
                )
            else:
                responseMessage = await flowise_query(
                    flowise_api_url, prompt, self.httpx_client
                )
            await send_room_message(
                self.client,
                room_id,
                reply_message=responseMessage.strip(),
                reply_to_event_id=reply_to_event_id,
                sender_id=sender_id,
                user_message=user_message,
            )
        except Exception as e:
            logger.error(e)
            await self.send_general_error_message(
                room_id, reply_to_event_id, sender_id, user_message
            )

    # !new command
    async def new(
        self,
        room_id,
        reply_to_event_id,
        sender_id,
        user_message,
        new_command,
    ) -> None:
        try:
            if "chat" in new_command:
                self.chatbot.reset(convo_id=sender_id)
                content = (
                    "New conversation created, please use !chat to start chatting!"
                )
            else:
                content = "Unkown keyword, please use !help to get available commands"

            await send_room_message(
                self.client,
                room_id,
                reply_message=content,
                reply_to_event_id=reply_to_event_id,
                sender_id=sender_id,
                user_message=user_message,
            )
        except Exception as e:
            logger.error(e)
            await self.send_general_error_message(
                room_id, reply_to_event_id, sender_id, user_message
            )

    # !pic command
    async def pic(
        self,
        room_id,
        prompt,
        replay_to_event_id,
        sender_id,
        user_message,
        reply_in_thread=False,
        thread_root_id=None,
    ):
        try:
            if self.image_generation_endpoint is not None:
                await self.client.room_typing(room_id, timeout=int(self.timeout) * 1000)
                # generate image
                image_path_list = await imagegen.get_images(
                    self.httpx_client,
                    self.image_generation_endpoint,
                    prompt,
                    self.image_generation_backend,
                    timeout=self.timeout,
                    api_key=self.openai_api_key,
                    output_path=self.base_path / "images",
                    n=1,
                    size=self.image_generation_size,
                    width=self.image_generation_width,
                    height=self.image_generation_height,
                    steps=self.sdwui_steps,
                    sampler_name=self.sdwui_sampler_name,
                    cfg_scale=self.sdwui_cfg_scale,
                    image_format=self.image_format,
                )
                # send image
                for image_path in image_path_list:
                    await send_room_image(
                        self.client,
                        room_id,
                        image_path,
                        replay_to_event_id,
                        reply_in_thread=reply_in_thread,
                        thread_root_id=thread_root_id,
                    )
                    await aiofiles.os.remove(image_path)
                await self.client.room_typing(room_id, typing_state=False)
            else:
                await send_room_message(
                    self.client,
                    room_id,
                    reply_message="Image generation endpoint not provided",
                    reply_to_event_id=replay_to_event_id,
                    sender_id=sender_id,
                    user_message=user_message,
                )
        except Exception as e:
            logger.error(e)
            await send_room_message(
                self.client,
                room_id,
                reply_message="Image generation failed",
                reply_to_event_id=replay_to_event_id,
                user_message=user_message,
                sender_id=sender_id,
            )

    # !help command
    async def help(
        self,
        room_id,
        reply_to_event_id,
        sender_id,
        user_message,
        reply_in_thread=False,
        thread_root_id=None,
    ):
        if self.custom_help_message:
            help_info = self.custom_help_message
        else:
            help_info = (
                "!gpt [prompt], generate a one time response without context conversation\n"
                + "!chat [prompt], chat with context conversation\n"
                + "!pic [prompt], Image generation by DALL-E-3 or LocalAI or stable-diffusion-webui\n"  # noqa: E501
                + "!new + chat, start a new conversation \n"
                + "!lc [prompt], chat using langchain api\n"
                + "quote a image and @bot with prompt, gpt vision function\n"
                + "@bot with prompt, create a thread level chatting\n"
                + "!help, help message"
            )  # noqa: E501

        await send_room_message(
            self.client,
            room_id,
            reply_message=help_info,
            sender_id=sender_id,
            user_message=user_message,
            reply_to_event_id=reply_to_event_id,
            reply_in_thread=reply_in_thread,
            thread_root_id=thread_root_id,
        )

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
        try:
            if self.password is not None:
                resp = await self.client.login(
                    password=self.password, device_name=DEVICE_NAME
                )
                if not isinstance(resp, LoginResponse):
                    logger.error("Login Failed")
                    await self.httpx_client.aclose()
                    await self.client.close()
                    sys.exit(1)
                logger.info("Successfully login via password")
                self.access_token = resp.access_token
            elif self.access_token is not None:
                self.client.restore_login(
                    user_id=self.user_id,
                    device_id=self.device_id,
                    access_token=self.access_token,
                )
                resp = await self.client.whoami()
                if not isinstance(resp, WhoamiResponse):
                    logger.error("Login Failed")
                    await self.close()
                    sys.exit(1)
                logger.info("Successfully login via access_token")
        except Exception as e:
            logger.error(e)
            await self.close()
            sys.exit(1)

    # import keys
    async def import_keys(self):
        resp = await self.client.import_keys(
            self.import_keys_path, self.import_keys_password
        )
        if isinstance(resp, EncryptionError):
            logger.error(f"import_keys failed with {resp}")
        else:
            logger.info("import_keys success, you can remove import_keys configuration")

    # sync messages in the room
    async def sync_forever(self, timeout=30000, full_state=True) -> None:
        await self.client.sync_forever(timeout=timeout, full_state=full_state)

    # get event from http
    async def get_event(self, room_id: str, event_id: str) -> dict:
        method, path = Api.room_get_event(self.access_token, room_id, event_id)
        url = self.homeserver + path
        if method == "GET":
            resp = await self.httpx_client.get(url)
            return resp.json()
        elif method == "POST":
            resp = await self.httpx_client.post(url)
            return resp.json()

    # download mxc
    async def download_mxc(self, mxc: str, filename: Optional[str] = None):
        response = await self.client.download(mxc, filename)
        return response
