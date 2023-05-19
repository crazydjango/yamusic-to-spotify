import argparse
import configparser
import logging
import spotipy
from transliterate import translit
from spotipy import SpotifyOAuth
from spotipy.exceptions import SpotifyException
from yandex_music import Client

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def initialize_yandex_client(user, config):
    try:
        access_token = config[user]['yandex_access_token']
        return Client(access_token).init()
    except Exception as e:
        logging.error(f'Error initializing Yandex Music client for user {user}: {e}')
        return None

def initialize_spotify_client(user, config):
    try:
        client_id = config[user]['spotify_client_id']
        client_secret = config[user]['spotify_client_secret']
        redirect_uri = config[user]['spotify_redirect_uri']
        return spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=client_id,
                                                         client_secret=client_secret,
                                                         redirect_uri=redirect_uri,
                                                         scope='playlist-modify-private'))
    except Exception as e:
        logging.error(f'Error initializing Spotify client for user {user}: {e}')
        return None

def transfer_playlists(user, yandex_client, spotify_client, list_only=False, select=False, liked=False):
    if not yandex_client or not spotify_client:
        logging.error(f'Yandex Music or Spotify client is not initialized for user {user}')
        return

    try:
        yandex_playlists = yandex_client.users_playlists_list()
    except Exception as e:
        logging.error(f'Error fetching Yandex Music playlists for user {user}: {e}')
        return
    
    # Logging for testing in case Yandex will return empty list
    #logging.info(f'Yandex Music playlists for user {user}: {yandex_playlists}')

    if list_only:
        print(f'Playlists for user {user}:')
        for i, playlist in enumerate(yandex_playlists):
            print(f'{i + 1}. {playlist["title"]}')
        return

    if select:
        print(f'Select playlists to export for user {user} (enter comma-separated playlist numbers):')
        for i, playlist in enumerate(yandex_playlists):
            print(f'{i + 1}. {playlist["title"]}')
        selected_indices = list(map(int, input().split(',')))
        yandex_playlists = [yandex_playlists[i - 1] for i in selected_indices]

    for playlist in yandex_playlists:
        playlist_name = playlist['title']

        try:
            playlist_id = playlist['kind']
            owner_id = playlist['owner']['uid']

            # Fetch tracks for the playlist
            if liked:
                playlist_name = "Liked Songs from Yandex"
                #playlist_tracks = yandex_client.users_likes_tracks().tracks
                tracks = yandex_client.users_likes_tracks().fetch_tracks()
            else:
                playlist_tracks = yandex_client.users_playlists(playlist_id, owner_id).tracks
                tracks = []
                for track in playlist_tracks:
                    tracks.append(track.track)

            playlist_info = {'title': playlist_name, 'tracks': tracks}
        except Exception as e:
            logging.error(f'Error fetching tracks for playlist "{playlist_name}" for user {user}: {e}')
            continue

        try:
            spotify_playlist = spotify_client.user_playlist_create(spotify_client.me()['id'], playlist_name, public=False)
            spotify_playlist_id = spotify_playlist['id']
        except SpotifyException as e:
            logging.error(f'Error creating Spotify playlist "{playlist_name}" for user {user}: {e}')
            continue

        track_uris = []

        for track_short in playlist_info['tracks']:
            track_name = ''
            artist_name = ''
            try:
                track_name = track_short.title
                artist_name = track_short.artists[0].name

                # Search for the track on Spotify without transliteration
                search_result = spotify_client.search(f'{track_name} artist:{artist_name}', type='track', limit=1)

                # If no results found, perform transliteration and search again
                if not search_result['tracks']['items']:
                    # Transliterate the artist name to match Spotify's representation
                    artist_name_transliterated = translit(artist_name, 'ru', reversed=True)
                    search_result = spotify_client.search(f'{track_name} artist:{artist_name_transliterated}', type='track', limit=1)
            except SpotifyException as e:
                logging.error(f'Error searching for track "{track_name}" by "{artist_name}" on Spotify for user {user}: {e}')
                continue
            except Exception as e:
                logging.error(f'Error processing track "{track_name}" by "{artist_name}" for user {user}: {e}')
                continue

            if search_result['tracks']['items']:
                track_uri = search_result['tracks']['items'][0]['uri']
                track_uris.append(track_uri)
            else:
                # Perform a new search based only on the original song name
                search_result = spotify_client.search(track_name, type='track', limit=5)

                # Display a numbered list of songs found
                print(f'Songs found on Spotify for "{track_name}" by "{artist_name}":')
                for i, item in enumerate(search_result['tracks']['items']):
                    song_info = f'{i + 1}. {item["name"]} - {", ".join([artist["name"] for artist in item["artists"]])}'
                    if item['album']['name']:
                        song_info += f' [{item["album"]["name"]}]'
                    print(song_info)
                    
                # Prompt the user to choose a song from the list
                while True:
                    choice = input('Choose a song to add (enter the number, 0 to skip): ')
                    if choice.isdigit() and 0 <= int(choice) <= len(search_result['tracks']['items']):
                        break

                # Add the chosen song to the playlist if a valid choice was made
                if choice != '0':
                    chosen_track = search_result['tracks']['items'][int(choice) - 1]
                    track_uri = chosen_track['uri']
                    track_uris.append(track_uri)
                else:
                    logging.warning(f'Song not found on Spotify: "{track_name}" by "{artist_name}"')

        try:
            spotify_client.playlist_add_items(spotify_playlist_id, track_uris)
        except SpotifyException as e:
            logging.error(f'Error adding tracks to Spotify playlist "{playlist_name}" for user {user}: {e}')

def main():
    # Read configuration
    config = configparser.ConfigParser()
    config.read('config.txt')

    # Check if there are any users in the config file
    if len(config.sections()) == 0:
        logging.error("No users found in the configuration file")
        return

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Transfer playlists from Yandex Music to Spotify.')
    parser.add_argument('--user', help='Specify a user from the configuration file')
    parser.add_argument('--list', action='store_true', help='List all playlists')
    parser.add_argument('--select', action='store_true', help='Select playlists to export')
    parser.add_argument('--liked', action='store_true', help='Export liked songs')
    args = parser.parse_args()

    if not args.user:
        print("Available users:")
        for i, user in enumerate(config.sections()):
            print(f"{i+1}. {user}")
        user_index = int(input("Choose a user (enter the number): ")) - 1
        if user_index < 0 or user_index >= len(config.sections()):
            logging.error("Invalid user selection")
            return
        selected_user = config.sections()[user_index]
    else:
        selected_user = args.user

    yandex_client = initialize_yandex_client(selected_user, config)
    spotify_client = initialize_spotify_client(selected_user, config)

    if not yandex_client or not spotify_client:
        return

    if args.list:
        transfer_playlists(selected_user, yandex_client, spotify_client, list_only=True)
    elif args.select:
        transfer_playlists(selected_user, yandex_client, spotify_client, select=True)
    elif args.liked:
        transfer_playlists(selected_user, yandex_client, spotify_client, liked=True)
    else:
        while True:
            print(f"\nUser: {selected_user}")
            print("Options:")
            print("1. List playlists")
            print("2. Export playlists")
            print("3. Export liked songs")
            print("4. Quit")
            choice = int(input("Choose an option (1-4): "))

            if choice == 1:
                transfer_playlists(selected_user, yandex_client, spotify_client, list_only=True)
            elif choice == 2:
                transfer_playlists(selected_user, yandex_client, spotify_client, select=True)
            elif choice == 3:
                transfer_playlists(selected_user, yandex_client, spotify_client, liked=True)
            elif choice == 4:
                break
            else:
                print("Invalid choice")

if __name__ == '__main__':
    main()
