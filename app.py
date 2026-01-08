import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image
import json
import io
from datetime import datetime
import time

# --- 頁面基本設定 ---
st.set_page_config(page_title="貝拉的名片夾", page_icon="📇")

# --- 初始化 Session State (用於重置輸入框) ---
if 'upload_key' not in st.session_state:
    st.session_state['upload_key'] = 0
if 'success_msg' not in st.session_state:
    st.session_state['success_msg'] = None

# --- 如果有成功的訊息，顯示在最上方並清空標記 ---
if st.session_state['success_msg']:
    st.success(st.session_state['success_msg'])
    st.balloons()
    st.session_state['success_msg'] = None

# --- 1. 定義 Gemini AI 功能 ---
def get_gemini_response(image_bytes):
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel(
            model_name="models/gemini-2.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )
        prompt = """
        你是專業的名片辨識助理。請分析這張名片圖片，並提取以下資訊。
        請務必以嚴格的 JSON 格式回傳，key 必須完全符合下列名稱。
        若欄位在圖片中找不到，請回傳空字串 ""。
        
        需要的欄位：
        - chinese_name (中文姓名)
        - english_name (英文姓名)
        - department (部門)
        - title (職位)
        - mobile (手機)
        - phone (電話)
        - email (信箱)
        - address (公司地址)
        """
        image = Image.open(io.BytesIO(image_bytes))
        response = model.generate_content([prompt, image])
        return json.loads(response.text)
    except Exception as e:
        if "429" in str(e) or "ResourceExhausted" in str(e):
            return "QUOTA_EXCEEDED"
        return None

# --- 2. 定義 Google Drive 上傳功能 ---
def upload_image_to_drive(image_bytes, file_name):
    try:
        scope = ['https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        
        service = build('drive', 'v3', credentials=creds)
        
        file_metadata = {
            'name': file_name,
            'parents': [st.secrets["DRIVE_FOLDER_ID"]]
        }
        
        media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype='image/jpeg')
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        st.error(f"Drive 上傳失敗: {e}")
        return None

# --- 3. 定義 Google Sheets 寫入功能 (已修改超連結邏輯) ---
def save_to_google_sheets(data, note, drive_link):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        sheet = client.open_by_url(st.secrets["SHEET_URL"]).sheet1
        existing_data = sheet.get_all_values()
        next_index = len(existing_data) if len(existing_data) > 0 else 1
        upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # --- 這裡修改了：將網址轉換成 Google Sheet 的超連結公式 ---
        if drive_link and "http" in drive_link:
            # 格式：=HYPERLINK("網址", "顯示文字")
            final_link = f'=HYPERLINK("{drive_link}", "名片連結")'
        else:
            final_link = "上傳失敗"
        # -----------------------------------------------------
        
        row = [
            next_index,
            data.get('chinese_name', ''),
            data.get('english_name', ''),
            data.get('department', ''),
            data.get('title', ''),
            data.get('mobile', ''),
            data.get('phone', ''),
            data.get('email', ''),
            data.get('address', ''),
            note,
            upload_time,
            final_link  # 放入轉換好的公式
        ]
        
        # 這裡改用 append_row 的 value_input_option='USER_ENTERED'
        # 這樣 Google Sheet 才會把 "=HYPERLINK(...)" 當作公式執行，而不是當作純文字
        sheet.append_row(row, value_input_option='USER_ENTERED')
        
        return True
    except Exception as e:
        st.error(f"資料庫連線失敗: {e}")
        return False

# --- 4. 建置網頁介面 ---
st.title("📇 貝拉的名片夾")
st.info("💡 提示：使用「拍照」時請將手機橫向持握。")

current_key = st.session_state['upload_key']

st.subheader("步驟 1：取得名片影像")
input_method = st.radio("選擇輸入方式", ["📸 拍照", "📂 上傳圖片"], horizontal=True, key=f"method_{current_key}")

final_image = None
if input_method == "📸 拍照":
    camera_file = st.camera_input("點擊下方按鈕拍照", label_visibility="collapsed", key=f"cam_{current_key}")
    if camera_file: final_image = camera_file
else:
    upload_file = st.file_uploader("請上傳名片圖片", type=['jpg', 'jpeg', 'png'], key=f"up_{current_key}")
    if upload_file:
        st.image(upload_file, caption="預覽", width=300)
        final_image = upload_file

st.subheader("步驟 2：輸入備註")
user_note = st.text_input("輸入備註", placeholder="選填...", key=f"note_{current_key}")

st.write("---")

if st.button("🚀 送出辨識並存檔", type="primary", use_container_width=True):
    if final_image is None:
        st.warning("⚠️ 請先提供名片照片！")
        st.stop()
        
    with st.spinner("AI 辨識中 & 圖片上傳中..."):
        image_bytes = final_image.getvalue()
        
        # 1. AI 辨識
        result = get_gemini_response(image_bytes)
        
        if result == "QUOTA_EXCEEDED":
            st.error("⚠️ 免費額度已用完")
        elif result:
            # 2. 上傳到 Google Drive
            file_name = f"名片_{result.get('chinese_name', '未命名')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            drive_link = upload_image_to_drive(image_bytes, file_name)
            
            # 3. 存入 Google Sheets (包含連結)
            if save_to_google_sheets(result, user_note, drive_link):
                st.session_state['success_msg'] = f"✅ 成功！已存檔並上傳圖片：{file_name}"
                st.session_state['upload_key'] += 1
                st.rerun()