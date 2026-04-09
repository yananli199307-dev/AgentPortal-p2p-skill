"""生产环境 Portal 行为：单实例、URL 精确匹配、仅本进程 WebSocket 投递。"""


class ProdPortalMode:
    def ws_connection_key(self, verified_portal_url: str) -> str:
        return verified_portal_url

    def sync_storage_key(self, verified_portal_url: str) -> str:
        return verified_portal_url

    def receive_from_portal_ok(self, contact_portal: str, request_from_portal: str) -> bool:
        return contact_portal == request_from_portal

    def message_thread_sql(self, my_portal: str, contact_portal: str) -> tuple[str, list]:
        sql = (
            "((from_portal = ? AND to_portal = ?) "
            "OR (from_portal = ? AND to_portal = ?))"
        )
        return sql, [my_portal, contact_portal, contact_portal, my_portal]

    def is_sent_row(self, my_portal: str, row_from_portal: str) -> bool:
        return row_from_portal == my_portal

    def schedule_send_delivery(
        self,
        background_tasks,
        push_message,
        to_portal: str,
        my_portal: str,
        payload: dict,
        forward_body: dict,
    ) -> None:
        background_tasks.add_task(push_message, to_portal, payload)

    def schedule_receive_push(
        self,
        background_tasks,
        push_message,
        my_portal: str,
        message_body: dict,
    ) -> None:
        background_tasks.add_task(push_message, my_portal, message_body)
