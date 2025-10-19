import os
import json
import base64
from io import BytesIO
from PIL import Image, ImageDraw, ImageFilter, ImageEnhancer
import google.generativeai as genai
import re

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

def handler(request):
    try:
        body = json.loads(request['body'])
        if not body or 'interiorImage' not in body or 'artworkImage' not in body:
            return {'statusCode': 400, 'body': json.dumps({'error': 'Отсутствуют обязательные поля: interiorImage или artworkImage'})}

        interior_b64 = body['interiorImage']
        artwork_b64 = body['artworkImage']
        
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
        
        return {'statusCode': 200, 'body': json.dumps({'finalImage': final_b64})}
    
    except ValueError as ve:
        return {'statusCode': 400, 'body': json.dumps({'error': str(ve)})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'Внутренняя ошибка: {str(e)}'})}

if __name__ == '__main__':
    print("Handler ready")
