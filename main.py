
import sys
import os
import re
import csv
import requests
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QTextEdit,
    QPushButton, QFileDialog, QProgressBar,
    QTableWidget, QTableWidgetItem, QMessageBox
)

APP_NAME = "Shopee Channel Video Downloader"


def safe_name(value):
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    return value.strip()[:100] or "video"


class DownloadWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    row = Signal(str, str, str)
    finished_ok = Signal()

    def __init__(self, entries, folder):
        super().__init__()
        self.entries = entries
        self.folder = Path(folder)

    def run(self):
        total = len(self.entries)

        for index, entry in enumerate(self.entries, 1):
            video_url, product_url = entry

            try:
                self.log.emit(f"Đang tải video {index}/{total}")

                response = requests.get(
                    video_url,
                    stream=True,
                    timeout=30,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                response.raise_for_status()

                content_type = response.headers.get(
                    "Content-Type", ""
                ).lower()

                if "video" not in content_type:
                    raise Exception(
                        "Nguồn không trả về tệp video trực tiếp."
                    )

                filename = safe_name(f"video_{index:04d}") + ".mp4"
                output = self.folder / filename

                with open(output, "wb") as file:
                    for chunk in response.iter_content(1024 * 256):
                        if chunk:
                            file.write(chunk)

                self.row.emit(
                    filename,
                    str(output),
                    product_url
                )
                self.log.emit(f"Đã tải: {filename}")

            except Exception as error:
                self.log.emit(
                    f"Lỗi video {index}: {error}"
                )

            self.progress.emit(int(index * 100 / total))

        self.finished_ok.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(APP_NAME)
        self.resize(1050, 700)

        self.output_folder = str(
            Path.home() / "ShopeeVideos"
        )
        Path(self.output_folder).mkdir(
            parents=True, exist_ok=True
        )

        self.records = []

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        title = QLabel(APP_NAME)
        title.setStyleSheet(
            "font-size:24px;font-weight:bold;padding:10px"
        )
        layout.addWidget(title)

        layout.addWidget(QLabel(
            "Nhập URL video trực tiếp, mỗi video một dòng."
        ))

        self.video_input = QTextEdit()
        self.video_input.setPlaceholderText(
            "URL video 1 | LINK SẢN PHẨM 1\n"
            "URL video 2 | LINK SẢN PHẨM 2\n\n"
            "Ví dụ:\n"
            "https://example.com/video.mp4 | https://shopee.vn/..."
        )
        layout.addWidget(self.video_input)

        folder_row = QHBoxLayout()
        self.folder_label = QLabel(self.output_folder)
        folder_button = QPushButton("Chọn thư mục lưu")
        folder_button.clicked.connect(self.choose_folder)

        folder_row.addWidget(self.folder_label)
        folder_row.addWidget(folder_button)
        layout.addLayout(folder_row)

        button_row = QHBoxLayout()

        self.download_button = QPushButton("TẢI VIDEO")
        self.download_button.clicked.connect(
            self.start_download
        )

        self.export_button = QPushButton("XUẤT EXCEL")
        self.export_button.clicked.connect(
            self.export_excel
        )

        button_row.addWidget(self.download_button)
        button_row.addWidget(self.export_button)
        layout.addLayout(button_row)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            "Tên video",
            "Đường dẫn video",
            "Link sản phẩm"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        layout.addWidget(QLabel("Nhật ký hoạt động"))
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumHeight(130)
        layout.addWidget(self.logs)

        self.worker = None

    def log(self, message):
        self.logs.append(message)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu video",
            self.output_folder
        )
        if folder:
            self.output_folder = folder
            self.folder_label.setText(folder)

    def start_download(self):
        lines = self.video_input.toPlainText().splitlines()
        entries = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            parts = line.split("|", 1)
            video_url = parts[0].strip()
            product_url = (
                parts[1].strip() if len(parts) > 1 else ""
            )

            parsed = urlparse(video_url)
            if parsed.scheme not in ("http", "https"):
                self.log(f"Bỏ qua URL không hợp lệ: {video_url}")
                continue

            entries.append((video_url, product_url))

        if not entries:
            QMessageBox.warning(
                self, "Thông báo",
                "Bạn chưa nhập URL video hợp lệ."
            )
            return

        self.records = []
        self.table.setRowCount(0)
        self.progress.setValue(0)
        self.download_button.setEnabled(False)

        self.worker = DownloadWorker(
            entries, self.output_folder
        )
        self.worker.progress.connect(self.progress.setValue)
        self.worker.log.connect(self.log)
        self.worker.row.connect(self.add_row)
        self.worker.finished_ok.connect(self.download_finished)
        self.worker.start()

    def add_row(self, name, path, product_url):
        index = self.table.rowCount()
        self.table.insertRow(index)

        for col, value in enumerate(
            [name, path, product_url]
        ):
            self.table.setItem(
                index, col, QTableWidgetItem(value)
            )

        self.records.append({
            "video": name,
            "path": path,
            "product_url": product_url
        })

    def download_finished(self):
        self.download_button.setEnabled(True)
        self.log("Hoàn tất quá trình tải.")

    def export_excel(self):
        if not self.records:
            QMessageBox.information(
                self, "Thông báo",
                "Chưa có dữ liệu để xuất."
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu danh sách Excel",
            "shopee_video_products.xlsx",
            "Excel (*.xlsx)"
        )

        if not path:
            return

        try:
            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Shopee Videos"

            sheet.append([
                "Tên video",
                "Đường dẫn video",
                "Link sản phẩm"
            ])

            for item in self.records:
                sheet.append([
                    item["video"],
                    item["path"],
                    item["product_url"]
                ])

            workbook.save(path)

            QMessageBox.information(
                self, "Thành công",
                "Đã xuất Excel thành công."
            )

        except Exception as error:
            QMessageBox.critical(
                self, "Lỗi", str(error)
            )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
