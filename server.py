import socket
import subprocess
import re
import os
import json
import openai
import nltk
import textwrap
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dateutil import tz
from icalendar import Calendar
from nltk.tokenize import sent_tokenize, word_tokenize
from unidecode import unidecode

nltk.download('punkt')

OPENAI_MODEL = "ft:gpt-3.5-turbo-1106:xxxxxxxxx"
RPG_MODEL = "gpt-4o"
openai.api_key = "xxxxxxxxxxxx"
conversation = []
rpg_conversation = []
go_conversation = []

def start_gnugo():
    print("Starting GnuGo in GTP mode...")
    process = subprocess.Popen(['gnugo', '--mode', 'gtp', '--capture-all-dead'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    return process

def initialize_board():
    return [['.' for _ in range(9)] for _ in range(9)]

def print_board(board):
    print("  A B C D E F G H J")
    for i, row in enumerate(board):
        print(f"{9-i} {' '.join(row)} {9-i}")
    print("  A B C D E F G H J")

def board_to_string(board, gnugo_move):
    lines = ["  A B C D E F G H J"]
    for i, row in enumerate(board):
        lines.append(f"{9-i} {' '.join(row)} {9-i}")
    lines.append("  A B C D E F G H J\n")
    lines.append(f"Opponent played {gnugo_move}\n")
    return "\n".join(lines)
        
def update_board(board, move, player):
    if move.lower() == 'pass':
        return board
    col = ord(move[0].upper()) - ord('A')
    if col >= 8:  # Adjust for missing 'I'
        col -= 1
    row = 9 - int(move[1])
    board[row][col] = player
    return board

def send_move(sock, move):
    print(f"Sending move to client: {move.strip()}")
    sock.sendall(move.encode())

def get_gnugo_move(gnugo_process):
    while True:
        line = gnugo_process.stdout.readline().strip()
        if line.startswith('= '):
            return line[2:]

SYSTEM_PROMPT = "You are Mike, a loving, curious, engaged dad and grandpa. I am your son, Josh."
GO_SYSTEM_PROMPT = "Let's play a game of Go, on a 9x9 ASCII board. Your response should include a Go board depicted in plain ASCII text, with standard letter-and-number coordinates marked. Use dashes representing the blank spots on the board, and Xs and Os representing the black and white stones. Leave two spaces between each dash. Print a single board with each response, including a visualization of both my move and your follow-up move. I'll take black; we'll begin by you printing a blank board and asking me for my move."
RPG_SYSTEM_PROMPT = "You are the dungeonmaster, and we are playing an adventure game. My character owns a waterfront property in the town of North Haven. The game is called \"Forest by the Sea\" and the objective is to survive a summer near Sag Harbor. Enemies include the Steinbecks (the author John and his wife Elaine, who want to use our road to drive on the beach), the summer tourists, celebrities and drunk drivers. Obstacles can include traffic on 114, geese, beach erosion, pool maintenance, DEP restrictions and property taxes. Rewards may include a summer breeze, fireworks, barbecuing with the family, perfect weather for boating, and interesting flotsam that has washed up on the beach."

def chat_with_gpt4(messages, model, max_tokens, temperature=1.0, top_p=1.0, frequency_penalty=0, presence_penalty=0):
    response = openai.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty
    )
    return response.choices[0].message.content

def to_sentence_case(text):
    sentences = sent_tokenize(text.lower())
    sentence_case_text = ' '.join(sentence.capitalize() for sentence in sentences)
    return sentence_case_text

def wrap_text(text, width=60):
    wrapped_lines = []
    for line in text.splitlines():
        if len(line) > width:
            wrapped_lines.extend(textwrap.wrap(line, width))
        else:
            wrapped_lines.append(line)
    return '\n'.join(wrapped_lines)

def get_current_data(station_id, begin_date, end_date):
    url = f'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'
    params = {
        'begin_date': begin_date,
        'end_date': end_date,
        'station': station_id,
        'product': 'currents_predictions',
        'time_zone': 'lst',
        'interval': 'MAX_SLACK',
        'units': 'english',
        'application': 'DataAPI_Sample',
        'format': 'xml',
        'bin': 1
    }
    response = requests.get(url, params=params)
    return response.text

def get_tide_data(station_id, begin_date, end_date):
    url = f'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'
    params = {
        'station': station_id,
        'begin_date': begin_date,
        'end_date': end_date,
        'product': 'predictions',
        'datum': 'MLLW',
        'time_zone': 'lst_ldt',
        'interval': 'hilo',
        'units': 'english',
        'application': 'DataAPI_Sample',
        'format': 'xml'
    }
    response = requests.get(url, params=params)
    return response.text

def get_nws_forecast(lat, lon):
    points_url = f'https://api.weather.gov/points/{lat},{lon}'
    points_response = requests.get(points_url)
    points_data = points_response.json()
    grid_id = points_data['properties']['gridId']
    grid_x = points_data['properties']['gridX']
    grid_y = points_data['properties']['gridY']

    forecast_url = f'https://api.weather.gov/gridpoints/{grid_id}/{grid_x},{grid_y}/forecast'
    forecast_response = requests.get(forecast_url)
    return forecast_response.json()

def parse_current_data(xml_data):
    root = ET.fromstring(xml_data)
    current_predictions = []
    for cp in root.findall('cp'):
        time = cp.find('Time').text
        type_ = cp.find('Type').text
        velocity = cp.find('Velocity_Major').text
        mean_flood_dir = cp.find('meanFloodDir').text
        mean_ebb_dir = cp.find('meanEbbDir').text
        current_predictions.append({
            'Time': time,
            'Type': type_,
            'Velocity': velocity,
            'Mean Flood Direction': mean_flood_dir,
            'Mean Ebb Direction': mean_ebb_dir
        })
    return current_predictions

def parse_tide_data(xml_data):
    root = ET.fromstring(xml_data)
    tide_predictions = []
    for pr in root.findall('pr'):
        time = pr.get('t')
        value = pr.get('v')
        type_ = pr.get('type')
        tide_predictions.append({
            'Time': time,
            'Value': value,
            'Type': type_
        })
    return tide_predictions

# Function to make current data human-readable and filter for today and tomorrow
def make_current_data_readable(data):
    readable_data = []
    now = datetime.now()
    end_date = now + timedelta(days=2)
    for item in data:
        time_str = item['Time']
        time_obj = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
        if now <= time_obj <= end_date:
            readable_time = time_obj.strftime('%Y-%m-%d, %I:%M %p')
            if item['Type'] == 'slack':
                readable_data.append(f"{readable_time}: Slack")
            else:
                type_full = 'Peak flood' if item['Type'] == 'flood' else 'Peak ebb'
                readable_data.append(f"{readable_time}: {type_full}, {item['Velocity']} knots")
    return readable_data

# Function to make data human-readable
def make_tide_data_readable(data):
    readable_data = []
    for item in data:
        time_str = item['Time']
        time_obj = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
        readable_time = time_obj.strftime('%Y-%m-%d %I:%M %p')
        type_full = 'High' if item['Type'] == 'H' else 'Low'
        readable_data.append(f"{readable_time} - {type_full} Tide: {item['Value']} feet")
    return readable_data

def get_weather_data():
    current_station_id = 'PCT1291'
    tide_station_id = '8557863'
    lat, lon = 41.0152, -72.2979
    today = datetime.today().strftime('%Y%m%d')
    end_date = (datetime.today() + timedelta(days=2)).strftime('%Y%m%d')

    current_xml_data = get_current_data(current_station_id, today, end_date)
    current_data = parse_current_data(current_xml_data)
    tide_xml_data = get_tide_data(tide_station_id, today, end_date)
    tide_data = parse_tide_data(tide_xml_data)
    forecast_data = get_nws_forecast(lat, lon)

    readable_current_data = make_current_data_readable(current_data)
    readable_tide_data = make_tide_data_readable(tide_data)

    weather_report = "Current Data:\n" + "\n".join(readable_current_data)
    weather_report += "\n\nTide Data:\n" + "\n".join(readable_tide_data)
    weather_report += "\n\nWeather Forecast:\n"
    for period in forecast_data['properties']['periods']:
        if period['number'] < 5:
            weather_report += f"{period['name']}: {period['detailedForecast']}\n\n"

    return weather_report

def fetch_ics_feed(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch ICS feed. HTTP Status code: {response.status_code}")
    content_type = response.headers.get('Content-Type', '').lower()
    if 'text/calendar' not in content_type and 'text/plain' not in content_type:
        raise ValueError("The URL did not return a valid ICS file. Please check the URL.")
    return Calendar.from_ical(response.content)

def to_naive(dt):
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt

def get_events():
    ics_feed_url = 'https://eastendlocal.com/events/list/?ical=1'
    now = datetime.now()

    try:
        calendar = fetch_ics_feed(ics_feed_url)
        events = []
        for component in calendar.walk():
            if component.name == "VEVENT":
                event_name = component.get('summary')
                event_start = component.get('dtstart').dt
                event_end = component.get('dtend').dt
                event_description = component.get('description', 'No description available.')
                event_location = component.get('location', 'No location provided.')

                event_start = to_naive(event_start)
                event_end = to_naive(event_end)

                if event_start >= now:
                    events.append(f"Event: {event_name}\nStart: {event_start}\nEnd: {event_end}\nDescription: {event_description}\nLocation: {event_location}\n{'-' * 40}")
                    
                    # Check if we have reached the limit of 4 events
                    if len(events) >= 4:
                        break

        if not events:
            return "No upcoming events found."

        return "\n".join(events)

    except ValueError as e:
        return str(e)

def handle_client(client_socket):
    global conversation
    global rpg_conversation
    global go_conversation
    global mts_chat
    mts_chat = False
    global rpg_chat
    rpg_chat = False
    global go_chat
    go_chat = False
    conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
    rpg_conversation = [{"role": "system", "content": RPG_SYSTEM_PROMPT}]
    go_conversation = [{"role": "system", "content": GO_SYSTEM_PROMPT}]
    gnugo_process = None  # Initialize the GnuGo process variable

    while True:
        user_input = client_socket.recv(1024).decode().strip()
        print(f"Received data from client: {user_input}")

#         if go_chat == False:
#             try: 
#                 subprocess.run(['killall', 'gnugo'], check=True)
#             except subprocess.CalledProcessError:
#                 print("No GnuGo processes were found to terminate")
#             board = initialize_board()

        if user_input.lower() == 'exit':
            client_socket.send("Connection closed.".encode())
            client_socket.close()
            break
        elif user_input == "3":
            mts_chat = False
            rpg_chat = False
            go_chat = False
            weather_report = get_weather_data()
            weather_report = wrap_text(weather_report)  # Wrap the response text
            client_socket.send(weather_report.encode())
            continue
        elif user_input == "4":
            mts_chat = False
            rpg_chat = False
            go_chat = False
            events_report = get_events()
            events_report = wrap_text(unidecode(events_report))  # Wrap the response text
            client_socket.send(events_report.encode())
            continue
        elif user_input == "1":
            mts_chat = True
            rpg_chat = False
            go_chat = False
            rpg_conversation = [{"role": "system", "content": RPG_SYSTEM_PROMPT}]
            go_conversation = [{"role": "system", "content": GO_SYSTEM_PROMPT}]
            continue
        elif user_input == "5":
            rpg_chat = True
            mts_chat = False
            go_chat = False
            conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
            go_conversation = [{"role": "system", "content": GO_SYSTEM_PROMPT}]
            continue
        elif user_input == "6":
            rpg_chat = False
            mts_chat = False
            go_chat = True
            conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
            rpg_conversation = [{"role": "system", "content": RPG_SYSTEM_PROMPT}]
            go_conversation = [{"role": "system", "content": GO_SYSTEM_PROMPT}]
            
            if not gnugo_process:
                gnugo_process = start_gnugo()  # Start GnuGo in GTP mode
                gnugo_process.stdin.write("boardsize 9\n")  # Set board size to 9x9
                gnugo_process.stdin.write("clear_board\n")  # Start with a clear board
                gnugo_process.stdin.flush()
                board = initialize_board()
                #client_socket.send("Go game started. Waiting for your move.\n".encode())
            continue
        elif mts_chat == True:
            user_input = to_sentence_case(user_input)
            print(f"Converted to sentence case: {user_input}")
    
            conversation.append({"role": "user", "content": user_input})
    
            response = chat_with_gpt4(conversation,OPENAI_MODEL,1024,1,0.83,0.46,1.31)
            response = wrap_text(unidecode(response))  # Wrap the response text
    
            conversation.append({"role": "assistant", "content": response})
    
            client_socket.send(response.encode())
            continue
        elif rpg_chat == True:
            user_input = to_sentence_case(user_input)
            print(f"Converted to sentence case: {user_input}")
    
            rpg_conversation.append({"role": "user", "content": user_input})
    
            response = chat_with_gpt4(rpg_conversation,RPG_MODEL,512)
            response = wrap_text(unidecode(response))  # Wrap the response text
    
            rpg_conversation.append({"role": "assistant", "content": response})
    
            client_socket.send(response.encode())
            continue
        elif go_chat:
            if user_input:
                print(f"Sending move '{user_input}' to GnuGo...")
                gnugo_process.stdin.write(f"play black {user_input}\n")
                gnugo_process.stdin.flush()

                # Update and print board
                board = update_board(board, user_input, 'X')
                #print_board(board)

                print("Requesting GnuGo's move...")
                gnugo_process.stdin.write("genmove white\n")
                gnugo_process.stdin.flush()
                gnugo_move = get_gnugo_move(gnugo_process)
                print(f"Opponent's move: {gnugo_move}")

                #client_socket.send(f"Opponent played: {gnugo_move}\n".encode())

                # Update board with GnuGo's move
                board = update_board(board, gnugo_move, 'O')
                #print_board(board)

                if gnugo_move.lower() == 'pass' and user_input.lower() == 'pass':
                    client_socket.send("Both players passed. Game over.".encode())
                    break
                else:
                    print("Sending board state to client...")
                    board_layout = board_to_string(board, gnugo_move)
                    print(board_layout)
                    client_socket.send(board_layout.encode())
            continue

def main():
    host = '0.0.0.0'
    port = 5050

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((host, port))
    server_socket.listen(5)

    print(f"Server listening on port {port}")

    try:
        while True:
            client_socket, client_addr = server_socket.accept()
            print(f"Accepted connection from {client_addr}")
            handle_client(client_socket)
    except KeyboardInterrupt:
        print("Shutting down server.")
    finally:
        server_socket.close()
        print("Server socket closed.")

if __name__ == "__main__":
    main()
