// src/components/Icons.jsx
// Bộ icon SVG line-style dùng chung (kế thừa màu qua currentColor).
// Thay cho emoji để giao diện chuyên nghiệp, nhất quán.
const Svg = ({ children, className = "w-5 h-5", strokeWidth = 1.75, ...rest }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
    {...rest}
  >
    {children}
  </svg>
);

export const SearchIcon = (p) => (
  <Svg {...p}><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></Svg>
);
export const ImageIcon = (p) => (
  <Svg {...p}><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-4.5-4.5L7 21" /></Svg>
);
export const TypeIcon = (p) => (
  <Svg {...p}><path d="M4 7V5h16v2M9 19h6M12 5v14" /></Svg>
);
export const MicIcon = (p) => (
  <Svg {...p}><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10a7 7 0 0 0 14 0M12 17v5" /></Svg>
);
export const ClockIcon = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Svg>
);
export const ChatIcon = (p) => (
  <Svg {...p}><path d="M21 12a8 8 0 0 1-11.3 7.3L3 21l1.7-6.7A8 8 0 1 1 21 12Z" /></Svg>
);
export const InboxIcon = (p) => (
  <Svg {...p}><path d="M4 13h4l1.5 3h5L16 13h4" /><path d="M5 13 6.5 5h11L19 13v6H5v-6Z" /></Svg>
);
export const SettingsIcon = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 6.8 19l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 6.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z" /></Svg>
);
export const KeyboardIcon = (p) => (
  <Svg {...p}><rect x="2" y="6" width="20" height="12" rx="2" /><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8" /></Svg>
);
export const RefreshIcon = (p) => (
  <Svg {...p}><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v5h-5" /></Svg>
);
export const PlusIcon = (p) => (
  <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>
);
export const CheckIcon = (p) => (
  <Svg {...p}><path d="M20 6 9 17l-5-5" /></Svg>
);
export const EyeIcon = (p) => (
  <Svg {...p}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></Svg>
);
export const FilmIcon = (p) => (
  <Svg {...p}><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4M3 12h18" /></Svg>
);
export const PlayIcon = (p) => (
  <Svg {...p}><path d="M6 4v16l14-8L6 4Z" /></Svg>
);
export const CloseIcon = (p) => (
  <Svg {...p}><path d="M18 6 6 18M6 6l12 12" /></Svg>
);
export const ChevronUpIcon = (p) => (
  <Svg {...p}><path d="m6 15 6-6 6 6" /></Svg>
);
export const ChevronDownIcon = (p) => (
  <Svg {...p}><path d="m6 9 6 6 6-6" /></Svg>
);
export const ChevronLeftIcon = (p) => (
  <Svg {...p}><path d="m15 6-6 6 6 6" /></Svg>
);
export const ChevronRightIcon = (p) => (
  <Svg {...p}><path d="m9 6 6 6-6 6" /></Svg>
);
export const TrashIcon = (p) => (
  <Svg {...p}><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" /></Svg>
);
export const DownloadIcon = (p) => (
  <Svg {...p}><path d="M12 3v12m0 0 4-4m-4 4-4-4M4 21h16" /></Svg>
);
export const CopyIcon = (p) => (
  <Svg {...p}><path d="M9 9h10v10a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V9Z M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></Svg>
);
export const SendIcon = (p) => (
  <Svg {...p}><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" /></Svg>
);
export const UploadIcon = (p) => (
  <Svg {...p}><path d="M12 21V9m0 0 4 4m-4-4-4 4M4 3h16" /></Svg>
);
export const SparklesIcon = (p) => (
  <Svg {...p}><path d="M12 3l1.8 4.9L18.7 9.7l-4.9 1.8L12 16.4l-1.8-4.9L5.3 9.7l4.9-1.8L12 3ZM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z" /></Svg>
);
export const HelpIcon = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1 .8-1 1.7M12 17h.01" /></Svg>
);
export const RocketIcon = (p) => (
  <Svg {...p}><path d="M5 15c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.9.7-2.2-.1-3a2.1 2.1 0 0 0-2.9 0ZM9 12a12 12 0 0 1 8-9c1 4-1 7-3 9M9 12l3 3M15 9l0 0" /><path d="M12 15c2 2 5 1 5 1M9 12s-1-3 1-5" /></Svg>
);
export const MenuIcon = (p) => (
  <Svg {...p}><path d="M4 6h16M4 12h16M4 18h16" /></Svg>
);
export const UsersIcon = (p) => (
  <Svg {...p}><path d="M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1" /><circle cx="9" cy="7" r="4" /><path d="M22 19v-1a4 4 0 0 0-3-3.87M16 3.13A4 4 0 0 1 16 11" /></Svg>
);
export const WifiOffIcon = (p) => (
  <Svg {...p}><path d="m2 2 20 20M8.5 16.5a5 5 0 0 1 7 0M5 12.9a10 10 0 0 1 3.5-2.3M2 8.8a15 15 0 0 1 4.2-2.8M19.8 12.9A10 10 0 0 0 16 10.3M22 8.8a15 15 0 0 0-9.7-3.7" /><path d="M12 20h.01" /></Svg>
);

/**
 * Logo AIC: chữ "A" khối trên nền navy - GIỮ TRÙNG với public/favicon.svg để tab
 * trình duyệt và header là cùng một nhận diện. Không dùng <Svg> vì đây là khối
 * đặc (fill), không phải icon line-style kế thừa currentColor.
 * Ruột chữ A vẽ ngược chiều thân chữ để fill-rule nonzero khoét thành lỗ.
 */
export const AlertTriangleIcon = (p) => (
  <Svg {...p}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></Svg>
);

export const AicMark = ({ className = "w-8 h-8" }) => (
  <svg className={className} viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <rect width="32" height="32" rx="8" fill="#0f172a" />
    <path d="M16 7 L24 25 H20.1 L18.6 21.3 H13.4 L11.9 25 H8 Z M16 13.2 L14.6 17.9 H17.4 Z" fill="#fff" />
  </svg>
);
