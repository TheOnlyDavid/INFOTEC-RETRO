import logging
from flask import current_app, jsonify
import json
import requests
import re
from datetime import datetime, timedelta

from app.services.openai_service import generate_response

# Diccionario para almacenar la última interacción de cada usuario
user_last_interaction = {}

# Opcional: Diccionario para guardar la opción seleccionada por cada usuario
user_selected_option = {}

def log_http_response(response):
    logging.info(f"Status: {response.status_code}")
    logging.info(f"Content-type: {response.headers.get('content-type')}")
    logging.info(f"Body: {response.text}")

def get_text_message_input(recipient, text):
    return json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    })

def get_interactive_menu_input(name):
    recipient = current_app.config["RECIPIENT_WAID"]
    menu_payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {
                "type": "text",
                "text": f"Bienvenido a Clínica Salud, {name}"
            },
            "body": {
                "text": "Por favor, selecciona una opción:"
            },
            "footer": {
                "text": "Responde seleccionando una opción"
            },
            "action": {
                "button": "Ver opciones",
                "sections": [
                    {
                        "title": "Menú Principal",
                        "rows": [
                            {
                                "id": "horarios",
                                "title": "Horarios",
                                "description": "Consulta nuestros horarios de atención"
                            },
                            {
                                "id": "Foto",
                                "title": "Foto",
                                "description": "Encuentra tu Foto"
                            },
                            {
                                "id": "soporte_general",
                                "title": "Soporte General",
                                "description": "Recibe asistencia general"
                            }
                        ]
                    }
                ]
            }
        }
    }
    return json.dumps(menu_payload)

def get_media_message_input(recipient):
    # Envía una imagen con la ubicación de la clínica
    return json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "image",
        "image": {
            "link": "https://i.imgur.com/XVxiHb7.jpeg"
        }
    })

def send_message(data):
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
    }
    url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{current_app.config['PHONE_NUMBER_ID']}/messages"
    try:
        response = requests.post(url, data=data, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.Timeout:
        logging.error("Timeout occurred while sending message")
        return jsonify({"status": "error", "message": "Request timed out"}), 408
    except requests.RequestException as e:
        logging.error(f"Request failed due to: {e}")
        return jsonify({"status": "error", "message": "Failed to send message"}), 500
    else:
        log_http_response(response)
        return response

def process_text_for_whatsapp(text):
    # Elimina contenido entre brackets
    pattern = r"\【.*?\】"
    text = re.sub(pattern, "", text).strip()
    # Convierte **texto** a *texto*
    pattern = r"\*\*(.*?)\*\*"
    replacement = r"*\1*"
    whatsapp_style_text = re.sub(pattern, replacement, text)
    return whatsapp_style_text

def process_whatsapp_message(body):
    # Extrae datos del mensaje entrante
    wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
    name = body["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"]
    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    
    now = datetime.now()
    enviar_menu = False
    if wa_id not in user_last_interaction or (now - user_last_interaction[wa_id] > timedelta(hours=2)):
        enviar_menu = True
    user_last_interaction[wa_id] = now

    if enviar_menu:
        # Envía el menú interactivo
        data = get_interactive_menu_input(name)
        send_message(data)
        return

    if message.get("type") == "interactive":
        interactive_obj = message.get("interactive")
        if "list_reply" in interactive_obj:
            selected_option = interactive_obj["list_reply"]["id"]
            user_selected_option[wa_id] = selected_option
            if selected_option == "Foto":
                # Envía la imagen con la ubicación de la clínica
                data = get_media_message_input(current_app.config["RECIPIENT_WAID"])
                send_message(data)
            elif selected_option == "horarios":
                response = generate_response("horarios", wa_id, name)
                response = process_text_for_whatsapp(response)
                data = get_text_message_input(current_app.config["RECIPIENT_WAID"], response)
                send_message(data)
            elif selected_option == "soporte_general":
                response = generate_response("soporte_general", wa_id, name)
                response = process_text_for_whatsapp(response)
                data = get_text_message_input(current_app.config["RECIPIENT_WAID"], response)
                send_message(data)
            return

    # Procesa mensajes de texto normales
    message_body = message.get("text", {}).get("body", "")
    response = generate_response(message_body, wa_id, name)
    response = process_text_for_whatsapp(response)
    data = get_text_message_input(current_app.config["RECIPIENT_WAID"], response)
    send_message(data)

def is_valid_whatsapp_message(body):
    """
    Verifica si el evento entrante tiene una estructura válida para un mensaje de WhatsApp.
    """
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )
