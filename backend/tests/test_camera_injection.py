from app.services.camera_injection import _parse_whatsapp_pid


def test_parse_whatsapp_pid_from_ios_process_list():
    processes = (
        "  744 /usr/libexec/mediaserverd\n"
        "  970 /var/containers/Bundle/Application/ABC/WhatsApp.app/WhatsApp\n"
    )
    assert _parse_whatsapp_pid(processes) == 970


def test_parse_whatsapp_pid_ignores_similar_process_names():
    processes = "123 /tmp/WhatsApp\n456 /Applications/WhatsAppHelper\n"
    assert _parse_whatsapp_pid(processes) is None
