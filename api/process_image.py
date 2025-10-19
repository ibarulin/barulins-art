import os
import base64
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFilter, ImageEnhancer
from io import BytesIO
import re

app = Flask(__name__)
CORS(app, origins=["https://barulins.art", "https://*.barulins.art"])

genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-pro')

def base64_to_image(base64_str):
    try:
        header, data = base64_str.split(',', 1)
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
    
    interior = interior.copy()
    x, y = placement['x'] - new_width // 2, placement['y'] - new_height // 2
    interior.paste(artwork, (x, y), artwork if artwork.mode == 'RGBA' else None)
    
    shadow = Image.new('RGBA', interior.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    for i in range(placement['wall_height']):
        alpha = int(50 * (i / placement['wall_height']))
        draw.rectangle([x, y + new_height - i, x + new_width, y + new_height], fill=(0, 0, 0, alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(5))
    interior = Image.alpha_composite(interior.convert('RGBA'), shadow)
    
    enhancer = ImageEnhancer.Contrast(interior)
    interior = enhancer.enhance(1.1)
    
    return interior

@app.route('/', methods=['POST'])
def process_image():
    try:
        data = request.get_json()
        if not data or 'interiorImage' not in data or 'artworkImage' not in data:
            return jsonify({'error': 'Отсутствуют обязательные поля: interiorImage или artworkImage'}), 400
        
        interior_b64 = data['interiorImage']
        artwork_b64 = data['artworkImage']
        
        interior_img = base64_to_image(interior_b64)
        artwork_img = base64_to_image(artwork_b64)
        
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
        
        return jsonify({'finalImage': final_b64})
    
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        return jsonify({'error': f'Внутренняя ошибка: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True)
