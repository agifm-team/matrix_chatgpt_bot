import markdown
from log import getlogger
from nio import AsyncClient

logger = getlogger()


async def send_room_message(
    client: AsyncClient,
    room_id: str,
    reply_message: str,
    sender_id: str = "",
    user_message: str = "",
    reply_to_event_id: str = "",
    thread_id = None,
    msg_limit=0,
    personal_api=None
) -> None:
    if reply_to_event_id == "":
        content = {
            "msgtype": "m.text",
            "body": reply_message,
            "format": "org.matrix.custom.html",
            "formatted_body": markdown.markdown(
                reply_message,
                extensions=["nl2br", "tables", "fenced_code"],
            ),
            "message_limit" : msg_limit,
        }
    else:
        body = "> <" + sender_id + "> " + user_message + "\n\n" + reply_message
        format = r"org.matrix.custom.html"
        formatted_body = (
            r'<mx-reply><blockquote><a href="https://matrix.to/#/'
            + room_id
            + r"/"
            + reply_to_event_id
            + r'">In reply to</a> <a href="https://matrix.to/#/'
            + sender_id
            + r'">'
            + sender_id
            + r"</a><br>"
            + user_message
            + r"</blockquote></mx-reply>"
            + markdown.markdown(
                reply_message,
                extensions=["nl2br", "tables", "fenced_code"],
            )
        )

        content = {
            "msgtype": "m.text",
            "body": body,
            "format": format,
            "formatted_body": formatted_body,
            "m.relates_to": {"m.in_reply_to": {"event_id": reply_to_event_id}},
            "message_limit" : msg_limit,
        }
    if thread_id is not None:
        thread_event_id = thread_id
    else:
        thread_event_id = reply_to_event_id
    content["m.relates_to"] = {
            'rel_type': 'm.thread', 
            'event_id': thread_event_id, 
            'is_falling_back': True, 
            'm.in_reply_to': {'event_id': reply_to_event_id}
        }
    if personal_api:
        content["api"] = True
    try:
        await client.room_send(
            room_id,
            message_type="m.room.message",
            content=content,
            ignore_unverified_devices=True,
        )
        await client.room_typing(room_id, typing_state=False)
    except Exception as e:
        logger.error(e)

async def send_text_message(client, room_id, message):
        await client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": message},
        )