from flask import Flask
app = Flask(__name__)

from flask import request, abort
from linebot import  LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, PostbackEvent, TextSendMessage, ImagemapSendMessage, BaseSize, MessageImagemapAction, URIImagemapAction, ImagemapArea, TemplateSendMessage, ButtonsTemplate, DatetimePickerTemplateAction, CarouselTemplate, CarouselColumn, MessageAction, PostbackAction, LocationSendMessage
from firebase import firebase

from urllib.parse import parse_qsl
import requests
import random

line_bot_api = LineBotApi('')
handler = WebhookHandler('')

GOOGLE_MAPS_API_KEY = ''
IPSTACK_API_KEY = ''
user_states = {}
photo_rec = {}

db_url = 'https://foodmap-db-default-rtdb.asia-southeast1.firebasedatabase.app/'
db = firebase.FirebaseApplication(db_url, None)

# Function to save user location to Firebase
def save_user_location(user_id, location):
    db.put('/user_locations', user_id, location)

# Function to retrieve user location from Firebase
def get_user_location(user_id):
    return db.get('/user_locations', user_id)

def save_likes(user_id, data):
    db.post(f'/likes/{user_id}', data=data)

def get_likes(user_id):
    likes = db.get('/likes', None)
    user_likes = {}
    if likes and user_id in likes:
        user_likes = likes[user_id]
    return user_likes

def remove_likes(user_id, key):
    path = f'/likes/{user_id}/{key}'
    response = db.delete('/', path)
    print(response)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    mtext = event.message.text.lower()
    food_types = ['cafe', 'restaurant', 'bar', 'night_club', 'shopping_mall']

    if mtext == '收藏的餐廳':
        reply = display_liked_restaurants(user_id)
        line_bot_api.reply_message(event.reply_token, reply)

    elif mtext == '更新地點':
        reply_text = '請輸入新的地點'
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        # Update user state to indicate that we're waiting for the new location
        user_states[user_id] = {'awaiting_location_update': True}
        print(user_states)

    elif mtext in food_types:
        user_states[user_id] = {'food_type': mtext}
        location = get_user_location(user_id)
        if location:
            places = get_nearby_restaurants(location=location, type=mtext)
            reply = format_places_message(places)
            line_bot_api.reply_message(event.reply_token, reply)

        else:
            reply_text = '請分享所在地點'
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

    elif user_id in user_states:
        if 'awaiting_location_update' in user_states[user_id]:
            # Update user location in Firebase
            save_user_location(user_id, mtext)
            del user_states[user_id]['awaiting_location_update']
            reply_text = '地點已更新'
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

        else:
            food_type = user_states[user_id]['food_type']
            places = get_nearby_restaurants(location=mtext, type=food_type)
            reply = format_places_message(places)
            line_bot_api.reply_message(event.reply_token, reply)
            del user_states[user_id]  # Clear the state after processing
        
    else:
        reply_text = '請選擇一個美食類型：cafe, restaurant, bar, night_club, shopping_mall'
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    user_id = event.source.user_id

    if data.startswith("details"): #導航
        _, name, address, lat, lng = data.split('|')
        reply_text = f"餐廳名稱: {name}\n地址: {address}\n"

        reply_text = LocationSendMessage(
            title = name,
            address = address,
            latitude = lat,
            longitude = lng
        )

        line_bot_api.reply_message(event.reply_token, reply_text)

    elif data.startswith("bookmark"): # 收藏餐廳
        _, name, address, lat, lng = data.split('|')
        save_likes(user_id, {'name': name, 'address': address, 'latitude': lat, 'longitude': lng})
        reply_text = f"{name} 已收藏"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

    elif data.startswith("unlike"): # 移除餐廳
        _, user_id, key, name = data.split('|')
        remove_likes(user_id, key)
        reply_text = f"{name} 已刪除"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

def display_liked_restaurants(user_id):
    liked_restaurants = get_likes(user_id)

    if not liked_restaurants:
        return TextSendMessage(text='尚未收藏餐廳')

    columns = []
    for restaurant_id, restaurant_info in liked_restaurants.items():
        column = CarouselColumn(
            # thumbnail_image_url=photo_rec[restaurant_info['photo_reference']],
            title=restaurant_info['name'][:40],
            text=" ",
            actions=[
                PostbackAction(label='導航', data=f'details|{restaurant_info["name"]}|{restaurant_info["address"]}|{restaurant_info["latitude"]}|{restaurant_info["longitude"]}'),
                PostbackAction(label='取消收藏', data=f'unlike|{user_id}|{restaurant_id}|{restaurant_info["name"]}')
            ]
        )
        columns.append(column)

    return TemplateSendMessage(
        alt_text='收藏列表',
        template=CarouselTemplate(columns=columns)
    )

def get_ip_address_info():
    response = requests.get(f'http://api.ipstack.com/check?access_key={IPSTACK_API_KEY}')
    data = response.json()
    print(data)
    return {'latitude': data['latitude'], 'longitude': data['longitude']}

def get_ip_address():
    response = requests.get('https://api.ipify.org?format=json')
    return response.json().get('ip')

def get_location_from_ip(ip):
    try:
        response = requests.get('https://ipapi.co/{ip}/json/'.format(ip=ip))
        data = response.json()
        print(data)
        return {'latitude': data['latitude'], 'longitude': data['longitude']}
    except Exception as e:
        print(e)
        return None

def get_nearby_restaurants(location=None, latitude=None, longitude=None, type=None):
    try:
        # 获取地理编码（经纬度）
        if location:
            geo_url = f'https://maps.googleapis.com/maps/api/geocode/json?address={location}&key={GOOGLE_MAPS_API_KEY}'
            geo_response = requests.get(geo_url)
            geo_data = geo_response.json()
            if not geo_data['results']:
                return []

            lat_lng = geo_data['results'][0]['geometry']['location']
            latitude = lat_lng['lat']
            longitude = lat_lng['lng']

        elif latitude is not None and longitude is not None:
            pass

        else:
            raise ValueError("Either 'location' or both 'latitude' and 'longitude' must be provided.")


        # 调用Google Places API获取餐厅信息
        places_url = 'https://maps.googleapis.com/maps/api/place/nearbysearch/json'
        params = {
            'location': f'{latitude},{longitude}',
            'radius': 1500,
            'type': type,
            'key': GOOGLE_MAPS_API_KEY
        }
        response = requests.get(places_url, params=params)
        return response.json().get('results', [])
    except Exception as e:
        print('aaaaa')
        print(e)
        return []

def format_places_message(places):
    if not places:
        return TextSendMessage(text='找不到 吃土了...')
    
    columns = []
    for place in random.sample(places, min(len(places), 5)):
        print(place)
        name = place.get('name', '未知名稱')
        address = place.get('vicinity', '未知地址')
        rating = place.get('rating', '無評分')
        lat = place['geometry']['location']['lat']
        lng = place['geometry']['location']['lng']
        open_now = place.get('opening_hours', {}).get('open_now', False)
        
        # print(len(name[:40])+len(address)+len(lat)+len(lng))
        if 'photos' in place:
            photo_reference = place['photos'][0]['photo_reference']
            photo_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=1024&photoreference={photo_reference}&key={GOOGLE_MAPS_API_KEY}"
        else:
            photo_url = 'https://via.placeholder.com/1024x1024'

        # print(photo_rec)
        # photo_rec[photo_reference[5:]] = photo_url
        column = CarouselColumn(
            thumbnail_image_url = photo_url,  
            title=name[:40],  # 标题最多40个字符
            text=f'營業中: {"是" if open_now else "否"}\n評分: {rating}\n',
            actions=[
                PostbackAction(label='導航', data=f'details|{name}|{address}|{lat}|{lng}'),
                PostbackAction(label='收藏餐廳', data=f'bookmark|{name}|{address}|{lat}|{lng}')
            ]
        )
        columns.append(column)

    carousel_template = CarouselTemplate(columns=columns)

    return TemplateSendMessage(alt_text='附近的餐廳推薦', template=carousel_template)

def format_opening_hours(weekday_text):
    print(weekday_text)
    if not weekday_text:
        return "無營業時間資料"
    return "\n".join(weekday_text)

if __name__ == '__main__':
    app.run(port = 3000)