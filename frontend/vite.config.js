import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // public/media/ chứa ~245K keyframe .webp - không cần watch cho HMR (FE
  // chỉ embed URL, không import trực tiếp), và vượt inotify max_user_watches
  // mặc định (~8K) khiến Vite crash với ENOSPC. Bỏ qua toàn bộ subtree.
  server: {
    // Lắng nghe trên mọi interface: khi thi 5 người, MỘT máy chạy cả BE lẫn FE
    // còn 4 máy kia mở http://<IP-máy-chủ>:5173. Mặc định Vite chỉ bind
    // localhost -> đồng đội không vào được.
    host: true,
    // strictPort: THÀ KHÔNG LÊN CÒN HƠN LÊN Ở CỔNG KHÁC. Mặc định Vite lặng lẽ
    // nhảy sang 5174 khi 5173 bận, mà cổng lại nằm trong hai thứ suy ra từ nó:
    //   - defaultBaseUrl() dựng địa chỉ backend từ host đang mở (api/apiClient.js)
    //   - MEDIA_BASE_URL của backend trỏ cứng vào 5173 (backend/.env)
    // Nhảy cổng thì cả hai trỏ trượt, mà triệu chứng chỉ là ảnh vỡ / gọi API
    // hỏng - không ai nghĩ tới cổng. Báo lỗi ngay lúc bật rõ ràng hơn nhiều.
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ['**/public/media/**'],
    },
    // Allow request từ ngrok tunnel (URL đổi mỗi session). Cần khi truy cập
    // FE qua ngrok từ browser hoặc khi BE trên Colab fetch media từ FE.
    // Vite 6+ chặn mặc định để chống DNS rebinding.
    allowedHosts: [
      '.ngrok-free.app',
      '.ngrok-free.dev',
      '.ngrok.io',
      '.trycloudflare.com',
      'localhost',
      '.eovtest.shop',
    ],
  },
})
