"""PreviewDialog - Shows file list before transfer with selection options"""

from typing import List
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QCheckBox,
    QGroupBox,
    QHeaderView,
    QAbstractItemView,
    QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from netcpy.models.file_info import FileInfo
from netcpy.utils.formatters import format_file_size, format_percentage


class PreviewDialog(QDialog):
    """Dialog showing files to be transferred before starting transfer"""

    def __init__(self, parent, files: List[FileInfo]):
        """Initialize PreviewDialog

        Args:
            parent: Parent widget
            files: List of FileInfo objects to display
        """
        super().__init__(parent)
        self.setWindowTitle("Transfer Preview")
        self.setMinimumSize(900, 600)
        self.files = files
        self.selected_files = files.copy()  # Start with all files selected

        self.setup_ui()
        self.populate_table()

    def setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout()

        # Summary section
        summary_group = QGroupBox("Summary")
        summary_layout = QHBoxLayout()

        self.total_label = QLabel()
        self.new_label = QLabel()
        self.existing_label = QLabel()

        summary_layout.addWidget(self.total_label)
        summary_layout.addWidget(self.new_label)
        summary_layout.addWidget(self.existing_label)
        summary_layout.addStretch()

        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)

        # Filter section
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))

        self.show_only_new_checkbox = QCheckBox("Show only new files")
        self.show_only_new_checkbox.toggled.connect(self.apply_filter)
        filter_layout.addWidget(self.show_only_new_checkbox)
        filter_layout.addStretch()

        layout.addLayout(filter_layout)

        # File table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Path", "Size", "Status", "Select"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)

        # Set column widths
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        layout.addWidget(self.table)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all)
        button_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self.deselect_all)
        button_layout.addWidget(deselect_all_btn)

        button_layout.addSpacing(20)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        self.start_btn = QPushButton("Start Transfer")
        self.start_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.start_btn)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def populate_table(self):
        """Populate the file table"""
        self.table.setRowCount(0)

        for file_info in self.files:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Path column
            path_item = QTableWidgetItem(file_info.relative_path)
            self.table.setItem(row, 0, path_item)

            # Size column
            size_item = QTableWidgetItem(format_file_size(file_info.size_bytes))
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 1, size_item)

            # Status column
            if file_info.is_new:
                status_item = QTableWidgetItem("New")
                status_item.setBackground(QColor(144, 238, 144))  # Light green
            else:
                status_item = QTableWidgetItem("Existing")
                status_item.setBackground(QColor(211, 211, 211))  # Light gray

            self.table.setItem(row, 2, status_item)

            # Select checkbox
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            checkbox.toggled.connect(self.update_selection)
            self.table.setCellWidget(row, 3, checkbox)

        self.update_summary()

    def update_summary(self):
        """Update the summary section with file counts and sizes"""
        total_files = len(self.files)
        new_files = sum(1 for f in self.files if f.is_new)
        existing_files = total_files - new_files

        total_size = sum(f.size_bytes for f in self.files)
        new_size = sum(f.size_bytes for f in self.files if f.is_new)

        selected_count = sum(
            1
            for row in range(self.table.rowCount())
            if isinstance(self.table.cellWidget(row, 3), QCheckBox)
            and self.table.cellWidget(row, 3).isChecked()
        )

        self.total_label.setText(f"Total: {total_files} files ({format_file_size(total_size)})")
        self.new_label.setText(f"New: {new_files} files ({format_file_size(new_size)})")
        self.existing_label.setText(f"Existing: {existing_files} files")

        # Update button text with selected count
        self.start_btn.setText(f"Start Transfer ({selected_count} selected)")

    def apply_filter(self):
        """Apply filter to show only new files if checkbox is checked"""
        show_only_new = self.show_only_new_checkbox.isChecked()

        for row in range(self.table.rowCount()):
            status_item = self.table.item(row, 2)
            is_new = status_item.text() == "New"
            self.table.setRowHidden(row, show_only_new and not is_new)

    def update_selection(self):
        """Update selected files list when checkboxes change"""
        self.selected_files = []

        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                checkbox = self.table.cellWidget(row, 3)
                if checkbox and checkbox.isChecked():
                    path_item = self.table.item(row, 0)
                    # Find the matching FileInfo object
                    for file_info in self.files:
                        if file_info.relative_path == path_item.text():
                            self.selected_files.append(file_info)
                            break

        self.update_summary()

    def select_all(self):
        """Select all files"""
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                checkbox = self.table.cellWidget(row, 3)
                if checkbox:
                    checkbox.setChecked(True)

    def deselect_all(self):
        """Deselect all files"""
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                checkbox = self.table.cellWidget(row, 3)
                if checkbox:
                    checkbox.setChecked(False)

    def get_selected_files(self) -> List[FileInfo]:
        """Get list of selected FileInfo objects

        Returns:
            List of selected FileInfo objects
        """
        return self.selected_files

    def accept(self):
        """Accept dialog and proceed with transfer"""
        self.update_selection()

        if not self.selected_files:
            QMessageBox.warning(self, "No Files Selected", "Please select at least one file to transfer.")
            return

        super().accept()
