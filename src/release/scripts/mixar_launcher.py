# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

# blender_launcher.py
# Place this file in: blender/release/scripts/startup/

import bpy
import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog
import subprocess
import json

class MixarLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Mixar Launcher")
        self.root.geometry("1000x600")
        self.root.configure(bg='#1a1a1a')
        
        # Store recent files
        self.config_file = Path.home() / ".mixar_launcher_config.json"
        self.recent_files = self.load_config()
        
        self.setup_ui()
        
    def load_config(self):
        """Load configuration and recent files"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                return config.get('recent_files', [])
        return []
    
    def save_config(self):
        """Save configuration"""
        config = {'recent_files': self.recent_files}
        with open(self.config_file, 'w') as f:
            json.dump(config, f)
    
    def setup_ui(self):
        """Create the UI similar to the mixar interface"""
        # Main container
        main_frame = tk.Frame(self.root, bg='#1a1a1a')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Left sidebar
        sidebar = tk.Frame(main_frame, bg='#1a1a1a', width=200)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 20))
        sidebar.pack_propagate(False)
        
        # Logo/Title
        title_label = tk.Label(sidebar, text="⬡ Mixar", 
                               font=('Arial', 18, 'bold'),
                               fg='#87c540', bg='#1a1a1a')
        title_label.pack(pady=(0, 30))
        
        # Import Model button
        import_btn = tk.Button(sidebar, text="Import Model",
                              bg='#87c540', fg='white',
                              font=('Arial', 11),
                              relief=tk.FLAT,
                              padx=20, pady=8,
                              command=self.import_model)
        import_btn.pack(pady=(0, 10))
        
        # Open button
        open_btn = tk.Button(sidebar, text="Open",
                            bg='#2a2a2a', fg='white',
                            font=('Arial', 11),
                            relief=tk.FLAT,
                            padx=20, pady=8,
                            command=self.open_file)
        open_btn.pack(pady=(0, 30))
        
        # Separator
        separator = tk.Frame(sidebar, height=1, bg='#3a3a3a')
        separator.pack(fill=tk.X, pady=(0, 20))
        
        # Menu items
        menu_items = ['Home', 'Templates', 'Learn']
        for item in menu_items:
            menu_btn = tk.Button(sidebar, text=item,
                               bg='#1a1a1a', fg='white',
                               font=('Arial', 10),
                               relief=tk.FLAT,
                               anchor='w',
                               padx=10,
                               command=lambda x=item: self.menu_action(x))
            menu_btn.pack(fill=tk.X, pady=2)
        
        # FILES section
        tk.Label(sidebar, text="FILES", 
                font=('Arial', 9),
                fg='#666666', bg='#1a1a1a',
                anchor='w').pack(fill=tk.X, pady=(30, 10), padx=10)
        
        file_items = ['Your files', 'Deleted']
        for item in file_items:
            file_btn = tk.Button(sidebar, text=item,
                               bg='#1a1a1a', fg='white',
                               font=('Arial', 10),
                               relief=tk.FLAT,
                               anchor='w',
                               padx=20,
                               command=lambda x=item: self.file_action(x))
            file_btn.pack(fill=tk.X, pady=2)
        
        # Right content area
        content_frame = tk.Frame(main_frame, bg='#1a1a1a')
        content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Banner
        banner = tk.Frame(content_frame, bg='#c0c0c0', height=150)
        banner.pack(fill=tk.X, pady=(0, 20))
        banner.pack_propagate(False)
        
        banner_label = tk.Label(banner, text="Welcome to Mixar",
                               font=('Arial', 24),
                               bg='#c0c0c0', fg='#333333')
        banner_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # Files section header
        files_header = tk.Frame(content_frame, bg='#1a1a1a')
        files_header.pack(fill=tk.X, pady=(0, 20))
        
        tk.Label(files_header, text="Your files",
                font=('Arial', 16, 'bold'),
                fg='white', bg='#1a1a1a').pack(side=tk.LEFT)
        
        # Filter and sort controls
        controls_frame = tk.Frame(files_header, bg='#1a1a1a')
        controls_frame.pack(side=tk.RIGHT)
        
        filter_var = tk.StringVar()
        filter_entry = tk.Entry(controls_frame, textvariable=filter_var,
                               bg='#2a2a2a', fg='white',
                               insertbackground='white')
        filter_entry.pack(side=tk.RIGHT, padx=5)
        
        tk.Label(controls_frame, text="Filter:",
                fg='#666666', bg='#1a1a1a').pack(side=tk.RIGHT, padx=5)
        
        sort_combo = ttk.Combobox(controls_frame, 
                                 values=['Date modified', 'Name', 'Size'],
                                 state='readonly', width=15)
        sort_combo.set('Date modified')
        sort_combo.pack(side=tk.RIGHT, padx=5)
        
        tk.Label(controls_frame, text="Sort by:",
                fg='#666666', bg='#1a1a1a').pack(side=tk.RIGHT, padx=5)
        
        # Files grid
        self.files_frame = tk.Frame(content_frame, bg='#1a1a1a')
        self.files_frame.pack(fill=tk.BOTH, expand=True)
        
        self.display_files()
        
        # Bottom buttons
        bottom_frame = tk.Frame(self.root, bg='#1a1a1a')
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=10)
        
        # New Project button
        new_btn = tk.Button(bottom_frame, text="New Project",
                          bg='#4a4a4a', fg='white',
                          font=('Arial', 11),
                          relief=tk.FLAT,
                          padx=20, pady=10,
                          command=self.new_project)
        new_btn.pack(side=tk.LEFT, padx=5)
        
        # Launch Mixar button
        launch_btn = tk.Button(bottom_frame, text="Launch Mixar",
                             bg='#87c540', fg='white',
                             font=('Arial', 11, 'bold'),
                             relief=tk.FLAT,
                             padx=30, pady=10,
                             command=self.launch_mixar)
        launch_btn.pack(side=tk.RIGHT, padx=5)
    
    def display_files(self):
        """Display recent files in a grid"""
        # Clear existing files
        for widget in self.files_frame.winfo_children():
            widget.destroy()
        
        # Create file cards
        for i, filepath in enumerate(self.recent_files[:8]):
            row = i // 4
            col = i % 4
            
            card = tk.Frame(self.files_frame, bg='#2a2a2a',
                          width=180, height=200,
                          relief=tk.RAISED, borderwidth=1)
            card.grid(row=row, column=col, padx=10, pady=10, sticky='nsew')
            card.pack_propagate(False)
            
            # Thumbnail area
            thumb = tk.Frame(card, bg='#c0c0c0', height=140)
            thumb.pack(fill=tk.X, padx=10, pady=10)
            
            # File name
            filename = os.path.basename(filepath)
            name_label = tk.Label(card, text=filename[:20],
                                fg='white', bg='#2a2a2a',
                                font=('Arial', 9))
            name_label.pack(pady=5)
            
            # Click to open
            card.bind("<Button-1>", lambda e, f=filepath: self.open_specific_file(f))
    
    def import_model(self):
        """Import a model file"""
        filetypes = (
            ('Mixar files', '*.blend'),
            ('FBX files', '*.fbx'),
            ('OBJ files', '*.obj'),
            ('All files', '*.*')
        )
        
        filename = filedialog.askopenfilename(
            title='Import Model',
            initialdir=os.path.expanduser('~'),
            filetypes=filetypes
        )
        
        if filename:
            self.add_recent_file(filename)
            self.display_files()
    
    def open_file(self):
        """Open a Mixar file"""
        filetypes = (
            ('Mixar files', '*.blend'),
            ('All files', '*.*')
        )
        
        filename = filedialog.askopenfilename(
            title='Open File',
            initialdir=os.path.expanduser('~'),
            filetypes=filetypes
        )
        
        if filename:
            self.add_recent_file(filename)
            self.launch_mixar(filename)
    
    def open_specific_file(self, filepath):
        """Open a specific file"""
        if os.path.exists(filepath):
            self.launch_mixar(filepath)
    
    def add_recent_file(self, filepath):
        """Add file to recent files list"""
        if filepath in self.recent_files:
            self.recent_files.remove(filepath)
        self.recent_files.insert(0, filepath)
        self.recent_files = self.recent_files[:20]  # Keep last 20
        self.save_config()
    
    def new_project(self):
        """Create a new project"""
        self.launch_mixar()
    
    def launch_mixar(self, filepath=None):
        """Launch Mixar with optional file"""
        self.root.destroy()
        
        # This will be replaced with actual Mixar launch
        # when integrated into Mixar's source
        if filepath:
            print(f"Launching Mixar with file: {filepath}")
            # In actual implementation:
            # sys.argv.append(filepath)
        else:
            print("Launching Mixar with new project")
    
    def menu_action(self, item):
        """Handle menu actions"""
        print(f"Menu action: {item}")
    
    def file_action(self, item):
        """Handle file section actions"""
        print(f"File action: {item}")
    
    def run(self):
        """Run the launcher"""
        self.root.mainloop()

# Integration point for Mixar
def show_launcher():
    """Show the launcher window before Mixar starts"""
    launcher = MixarLauncher()
    launcher.run()
    return True  # Continue to launch Mixar

# For testing standalone
if __name__ == "__main__":
    show_launcher()