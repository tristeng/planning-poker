from pp.model import MessageType, Player


class TestMessageType:
    def test_is_admin_message(self):
        admin_message_types = [MessageType.RESET, MessageType.REVEAL]
        for msg_type in admin_message_types:
            assert MessageType.is_admin_message(msg_type) is True

        non_admin_msg_types = [msg for msg in list(MessageType) if msg not in admin_message_types]
        for msg_type in non_admin_msg_types:
            assert MessageType.is_admin_message(msg_type) is False

    def test_print_player(self):
        player = Player(username="Alice")
        assert f"Alice ({player.id})" == str(player)
