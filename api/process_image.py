import os
import json
import base64
from io import BytesIO
from PIL import Image, ImageDraw, ImageFilter, ImageEnhancer
import google.generativeai as genai
import re

# --- Никаких изменений в этой части ---
genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-pro')

def base64_to_image(base64_str):
    try:
        # Убираем префикс, если он есть
        if ',' in base64_str:
            header, data = base64_str.split(',', 1)
        else:
            data = base64_str
        img_data = base64.b64decode(data)
        return Image.open(BytesIO(img_data))
    except Exception as e:
        raise ValueError(f"Ошибка декодирования Base64: {str(e)}")

def parse_gemini_response(response_text):
    try:
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return {
                'x': int(data.get('x', 960)),
                'y': int(data.get('y', 324)),
                'scale': float(data.get('scale', 0.8)),
                'rotation': float(data.get('rotation', 0)),
                'wall_height': int(data.get('wall_height', 600))
            }
        else:
            return {'x': 960, 'y': 324, 'scale': 0.8, 'rotation': 0, 'wall_height': 600}
    except:
        return {'x': 960, 'y': 324, 'scale': 0.8, 'rotation': 0, 'wall_height': 600}

def composite_images(interior, artwork, placement):
    art_width, art_height = artwork.size
    new_width = int(art_width * placement['scale'])
    new_height = int(art_height * placement['scale'])
    artwork = artwork.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    if placement['rotation'] != 0:
        artwork = artwork.rotate(placement['rotation'], expand=True)
    
    interior = interior.copy().convert('RGBA')
    x, y = placement['x'] - new_width // 2, placement['y'] - new_height // 2
    
    # Создаем временный слой для картины, чтобы вставить ее
    artwork_layer = Image.new('RGBA', interior.size, (0, 0, 0, 0))
    artwork_layer.paste(artwork, (x, y), artwork if artwork.mode == 'RGBA' else None)
    
    # Комбинируем интерьер и слой с картиной
    interior = Image.alpha_composite(interior, artwork_layer)
    
    # Логика тени остается прежней, но применяется к RGBA изображению
    shadow = Image.new('RGBA', interior.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    shadow_intensity = 50
    shadow_blur = 5
    draw.rectangle([x + shadow_blur, y + shadow_blur, x + new_width + shadow_blur, y + new_height + shadow_blur], fill=(0, 0, 0, shadow_intensity))
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
    
    # Комбинируем результат с тенью
    final_img_with_shadow = Image.alpha_composite(interior, shadow)
    
    enhancer = ImageEnhancer.Contrast(final_img_with_shadow)
    final_img_enhanced = enhancer.enhance(1.1)
    
    return final_img_enhanced.convert('RGB')

# --- ГЛАВНОЕ ИЗМЕНЕНИЕ ЗДЕСЬ ---
# Эта функция теперь называется handler, как и требует Vercel
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            data = json.loads(body)

            if not data or 'interiorImage' not in data or 'artworkImage' not in data:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Отсутствуют обязательные поля'}).encode())
                return

            interior_img = base64_to_image(data['interiorImage'])
            artwork_img = base64_to_image(data['artworkImage'])
            
            prompt = """
            Ты — профессиональный ассистент по дизайну интерьеров. 
            На первом изображении (интерьер) найди самую подходящую стену для размещения картины. 
            Учти перспективу, освещение и тени в комнате. 
            Верни ТОЛЬКО JSON с координатами для размещения второй картины (artwork): 
            {"x": центр_x (пиксели, от 0 до ширины интерьера), "y": верх_y (от 0), "scale": 0.5-1.0 (масштаб), "rotation": угол_в_градусах (обычно 0-5), "wall_height": высота_стены_пиксели (для теней)}.
            Предполагай размер интерьера 1920x1080. Не добавляй текст вне JSON.
            """
            
            response = model.generate_content([prompt, interior_img, artwork_img])
            placement = parse_gemini_response(response.text)
            
            final_img = composite_images(interior_img, artwork_img, placement)
            
            buffered = BytesIO()
            final_img.save(buffered, format="PNG")
            final_b64 = base64.b64encode(buffered.getvalue()).decode()
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'finalImage': final_b64}).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': f'Внутренняя ошибка: {str(e)}'}).encode())
