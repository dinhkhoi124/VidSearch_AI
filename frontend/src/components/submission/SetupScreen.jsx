// src/components/submission/SetupScreen.jsx
// Màn hình đầu vòng thi: khi chưa có đề và chưa có đáp án nào thì việc duy nhất
// đáng làm là NHẬP GÓI ĐỀ. Cho nó cả khay thay vì nhét một ô kéo-thả bé xíu lên
// đầu danh sách như trước - và một khi đã có đề thì màn này biến mất hẳn.
//
// `reopened`: gọi lại giữa vòng từ nút "Nhập lại gói đề" (popover ⚙). Lúc đó đề
// cũ vẫn còn nguyên nên phải đổi lời và mở đường LUI - khác hẳn lần đầu, nơi
// không có gì để quay về.
import QueryPackageImport from "../QueryPackageImport";
import { NumQuestionsField } from "../QuestionSwitcher";
import { InboxIcon, UploadIcon } from "../Icons";

function SetupScreen({ basket, onDone, reopened = false }) {
  return (
    <div className="flex-1 overflow-y-auto p-5">
      <div className="mx-auto flex max-w-sm flex-col gap-5 pt-8">
        <div className="text-center">
          {reopened ? (
            <UploadIcon className="mx-auto w-10 h-10 text-slate-300" />
          ) : (
            <InboxIcon className="mx-auto w-10 h-10 text-slate-300" />
          )}
          <h2 className="mt-2 text-[15px] font-semibold text-slate-700">
            {reopened ? "Nhập lại gói đề" : "Bắt đầu một vòng thi"}
          </h2>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
            {reopened ? (
              <>
                Thả gói đề mới (<span className="font-semibold text-slate-500">.zip</span> hoặc các file{" "}
                <span className="font-semibold text-slate-500">query-*.txt</span>) vào đây, rồi chọn gộp vào đề
                đang làm hay dựng lại từ đầu cho vòng mới.
              </>
            ) : (
              <>
                Thả file <span className="font-semibold text-slate-500">.zip</span> gói đề BTC phát vào đây - số
                câu, loại task, Query ID và đề bài của từng câu sẽ tự dựng theo gói, khỏi gõ tay từng câu.
              </>
            )}
          </p>
        </div>

        <QueryPackageImport basket={basket} onImported={onDone} big />

        <div className="flex items-center justify-center gap-2 border-t border-slate-200 pt-4 text-xs text-slate-400">
          {reopened ? (
            <button
              onClick={onDone}
              className="rounded-md px-2 py-1 font-semibold text-blue-600 transition-colors hover:bg-blue-50"
            >
              Quay lại đề đang làm
            </button>
          ) : (
            <>
              Chưa có file? Đặt số câu
              <NumQuestionsField value={basket.numQuestions} onCommit={basket.setNumQuestions} />
              <button
                onClick={onDone}
                className="rounded-md px-2 py-1 font-semibold text-blue-600 transition-colors hover:bg-blue-50"
              >
                rồi bắt đầu
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default SetupScreen;
