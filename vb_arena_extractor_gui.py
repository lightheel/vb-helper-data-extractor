#!/usr/bin/env python3
"""
GUI Wrapper for Vital Bracelet Arena Asset Extractor
Uses built-in tkinter (no extra dependencies)
"""

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import threading
import sys
import os
from pathlib import Path
import logging
from vb_arena_extractor import MasterExtractor

class ExtractorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("VBHelper Battle Extractor")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        # Variables
        self.apk_path = tk.StringVar()
        self.extraction_in_progress = False
        self.extractor = None
        self.should_exit = False
        self.extraction_thread = None
        
        # Setup window close handler
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Setup UI
        self.setup_ui()
        
        # Redirect logging to text widget
        self.setup_logging()
    
    def setup_ui(self):
        # Title Frame
        title_frame = tk.Frame(self.root, bg="#2c3e50", height=60)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)
        
        title = tk.Label(
            title_frame,
            text="VBHelper Battle Extractor",
            font=("Arial", 18, "bold"),
            bg="#2c3e50",
            fg="white"
        )
        title.pack(pady=15)
        
        # Main Container
        main_frame = tk.Frame(self.root, padx=20, pady=10)
        main_frame.pack(fill="both", expand=True)
        
        # APK Selection Frame
        apk_frame = tk.LabelFrame(main_frame, text="APK File Selection", padx=10, pady=10)
        apk_frame.pack(fill="x", pady=10)
        
        apk_entry = tk.Entry(
            apk_frame,
            textvariable=self.apk_path,
            font=("Arial", 10),
            width=60
        )
        apk_entry.pack(side="left", padx=5, fill="x", expand=True)
        
        browse_btn = tk.Button(
            apk_frame,
            text="Browse...",
            command=self.browse_apk,
            width=12,
            font=("Arial", 10)
        )
        browse_btn.pack(side="right", padx=5)
        
        # Extract Button Frame
        button_frame = tk.Frame(main_frame)
        button_frame.pack(pady=15)
        
        self.extract_btn = tk.Button(
            button_frame,
            text="Extract Assets",
            command=self.start_extraction,
            font=("Arial", 12, "bold"),
            bg="#3498db",
            fg="white",
            activebackground="#2980b9",
            activeforeground="white",
            width=20,
            height=2,
            cursor="hand2"
        )
        self.extract_btn.pack()
        
        # Progress Frame
        progress_frame = tk.Frame(main_frame)
        progress_frame.pack(fill="x", pady=5)
        
        self.progress_label = tk.Label(
            progress_frame,
            text="Ready to extract",
            font=("Arial", 10),
            fg="#27ae60"
        )
        self.progress_label.pack()
        
        # Progress Bar
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            mode='indeterminate',
            length=400
        )
        self.progress_bar.pack(pady=5)
        
        # Counters Frame
        counters_frame = tk.Frame(progress_frame)
        counters_frame.pack(pady=5)
        
        # Game Objects Counter
        game_objects_counter_frame = tk.Frame(counters_frame)
        game_objects_counter_frame.pack(side="left", padx=10)
        
        tk.Label(
            game_objects_counter_frame,
            text="Game Objects Extracted:",
            font=("Arial", 10),
            fg="#7f8c8d"
        ).pack(side="left", padx=5)
        
        self.game_objects_counter_label = tk.Label(
            game_objects_counter_frame,
            text="0",
            font=("Arial", 10, "bold"),
            fg="#e67e22"
        )
        self.game_objects_counter_label.pack(side="left", padx=5)
        
        # Initialize counters
        self.game_objects_count = 0
        
        # Log Output Frame
        log_frame = tk.LabelFrame(main_frame, text="Extraction Log", padx=10, pady=10)
        log_frame.pack(fill="both", expand=True, pady=10)
        
        # Log Text Widget with Scrollbar
        log_container = tk.Frame(log_frame)
        log_container.pack(fill="both", expand=True)
        
        self.log_text = scrolledtext.ScrolledText(
            log_container,
            wrap="word",
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#ffffff",
            selectbackground="#3d3d3d"
        )
        self.log_text.pack(fill="both", expand=True)
        
        # Status Bar
        status_frame = tk.Frame(self.root, bg="#34495e", height=30)
        status_frame.pack(fill="x", side="bottom")
        status_frame.pack_propagate(False)
        
        self.status_label = tk.Label(
            status_frame,
            text="Ready",
            bg="#34495e",
            fg="white",
            font=("Arial", 9),
            anchor="w",
            padx=10
        )
        self.status_label.pack(fill="x")
    
    def setup_logging(self):
        """Redirect logging to the text widget"""
        class TextHandler(logging.Handler):
            def __init__(self, text_widget, root):
                super().__init__()
                self.text_widget = text_widget
                self.root = root
            
            def emit(self, record):
                msg = self.format(record)
                # Use root.after to ensure thread-safe GUI updates
                self.root.after(0, self._append_text, msg)
            
            def _append_text(self, msg):
                self.text_widget.insert("end", msg + "\n")
                self.text_widget.see("end")
                # Limit log size to prevent memory issues
                lines = int(self.text_widget.index("end-1c").split(".")[0])
                if lines > 10000:
                    self.text_widget.delete(1.0, "5000.0")
        
        handler = TextHandler(self.log_text, self.root)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
    
    def browse_apk(self):
        """Open file dialog to select APK"""
        filename = filedialog.askopenfilename(
            title="Select APK File",
            filetypes=[("APK files", "*.apk"), ("All files", "*.*")],
            initialdir=os.path.expanduser("~")
        )
        if filename:
            self.apk_path.set(filename)
            self.log_message(f"Selected APK: {filename}")
            self.update_status(f"APK selected: {os.path.basename(filename)}")
    
    def log_message(self, message):
        """Add message to log widget"""
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.root.update_idletasks()
    
    def update_status(self, message):
        """Update status bar"""
        self.status_label.config(text=message)
        self.root.update_idletasks()
    
    def update_game_objects_counter(self, count):
        """Update game objects counter display (thread-safe)"""
        self.game_objects_count = count
        self.root.after(0, self._update_game_objects_counter_ui, count)
    
    def _update_game_objects_counter_ui(self, count):
        """Update game objects counter UI (called in main thread)"""
        self.game_objects_counter_label.config(text=str(count))
        self.root.update_idletasks()
    
    def on_closing(self):
        """Handle window close event"""
        if self.extraction_in_progress:
            # Ask user if they want to cancel extraction
            # Use after() to ensure this runs in the main thread
            self.root.after(0, self._ask_cancel_extraction)
        else:
            self.cleanup_and_exit()
    
    def _ask_cancel_extraction(self):
        """Ask user if they want to cancel extraction (called in main thread)"""
        if messagebox.askokcancel("Quit", "Extraction is in progress. Do you want to cancel and exit?"):
            self.should_exit = True
            self.extraction_in_progress = False
            logging.info("User requested exit - cancelling extraction...")
            self.cleanup_and_exit()
    
    def cleanup_and_exit(self):
        """Clean up resources and exit"""
        try:
            # Set flag to prevent any further operations
            self.should_exit = True
            self.extraction_in_progress = False
            
            # Stop progress bar if running
            try:
                self.progress_bar.stop()
            except:
                pass
            
            # Destroy window first (non-blocking)
            try:
                self.root.quit()
            except:
                pass
            
            try:
                self.root.destroy()
            except:
                pass
            
            # Quick cleanup (don't wait for PNGs - they'll finish in background)
            if self.extractor:
                try:
                    # Don't wait for PNG saves - just shutdown executor quickly
                    self.extractor.cleanup_temp_folders(wait_for_pngs=False)
                except:
                    pass  # Ignore cleanup errors on exit
            
        except Exception as e:
            pass  # Ignore all errors on exit
        finally:
            # Force immediate exit - don't wait for anything
            import os
            import threading
            # Give a tiny moment for window to close, then force exit
            def force_exit():
                import time
                time.sleep(0.1)  # 100ms grace period
                os._exit(0)
            threading.Thread(target=force_exit, daemon=True).start()
            # Also try immediate exit
            os._exit(0)
    
    def start_extraction(self):
        """Start extraction in a separate thread"""
        if self.extraction_in_progress:
            messagebox.showwarning("Extraction in Progress", "Please wait for the current extraction to complete.")
            return
        
        apk_file = self.apk_path.get().strip()
        
        if not apk_file:
            # Check if temp_extraction exists
            if not Path("temp_extraction").exists():
                messagebox.showerror("Error", "Please select an APK file or ensure temp_extraction folder exists.")
                return
        
        if apk_file and not Path(apk_file).exists():
            messagebox.showerror("Error", f"APK file not found: {apk_file}")
            return
        
        # Disable button and start extraction
        self.extraction_in_progress = True
        self.extract_btn.config(state="disabled", text="Extracting...", bg="#95a5a6")
        self.progress_label.config(text="Extraction in progress...", fg="#e74c3c")
        self.progress_bar.start(10)
        self.log_text.delete(1.0, "end")
        self.update_status("Extraction in progress...")
        
        # Reset counters
        self.game_objects_count = 0
        self.game_objects_counter_label.config(text="0")
        
        # Start extraction in thread
        self.extraction_thread = threading.Thread(target=self.run_extraction, args=(apk_file,), daemon=True)
        self.extraction_thread.start()
    
    def run_extraction(self, apk_file):
        """Run extraction (called in thread)"""
        try:
            # Check if we should exit before starting
            if self.should_exit:
                return
            
            # Configure logging - always use INFO level
            logging.getLogger().setLevel(logging.INFO)
            
            logging.info("=" * 50)
            logging.info("Starting extraction process...")
            logging.info("=" * 50)
            
            # Create extractor with callback for stats updates
            logging.info("Creating Extractor instance...")
            self.extractor = MasterExtractor()
            
            # Set callback to update game objects counter when stats are extracted
            def on_stats_extracted(count):
                self.update_game_objects_counter(count)
            
            self.extractor.set_stats_callback(on_stats_extracted)
            logging.info("Extractor created successfully")
            
            # Check again before starting extraction
            if self.should_exit:
                logging.info("Extraction cancelled before starting")
                return
            
            # Run extraction
            if apk_file:
                logging.info(f"Starting extraction from APK: {apk_file}")
                logging.info(f"APK file exists: {Path(apk_file).exists()}")
                if not self.should_exit:
                    logging.info("Calling process_main_apk...")
                    self.extractor.process_main_apk(apk_file)
                    logging.info("process_main_apk completed")
            else:
                logging.info("Starting extraction from temp_extraction folder")
                logging.info(f"temp_extraction exists: {Path('temp_extraction').exists()}")
                if not self.should_exit:
                    logging.info("Calling run_extraction...")
                    self.extractor.run_extraction()
                    logging.info("run_extraction completed")
            
            # Check if we were cancelled
            if self.should_exit:
                logging.info("Extraction was cancelled by user")
                return
            
            # Log extraction results
            logging.info("=" * 50)
            logging.info("Extraction completed - checking results...")
            logging.info(f"Audio files extracted: {len(self.extractor.extracted_audio)}")
            logging.info(f"Attack sprites: {getattr(self.extractor, 'total_atksprites', 0)}")
            logging.info(f"Battle backgrounds: {getattr(self.extractor, 'total_battlebgs', 0)}")
            logging.info(f"Stats data: {sum(getattr(self.extractor, 'extracted_stats', {}).values())}")
            logging.info("=" * 50)
            
            # Success
            self.root.after(0, self.extraction_complete, True, "Extraction completed successfully!")
            
        except Exception as e:
            if not self.should_exit:
                error_msg = f"Error during extraction: {str(e)}"
                logging.error("=" * 50)
                logging.error("EXTRACTION FAILED!")
                logging.error(error_msg)
                logging.error("=" * 50, exc_info=True)
                self.root.after(0, self.extraction_complete, False, error_msg)
        finally:
            # Cleanup (but don't delete temp folders - user might want to inspect them)
            if not self.should_exit:
                logging.info("Extraction thread finished")
    
    def extraction_complete(self, success, message):
        """Called when extraction completes"""
        self.extraction_in_progress = False
        self.progress_bar.stop()
        self.extract_btn.config(state="normal", text="Extract Assets", bg="#3498db")
        
        if success:
            self.progress_label.config(text="Extraction complete!", fg="#27ae60")
            self.update_status("Extraction completed successfully")
            messagebox.showinfo("Success", message)
        else:
            self.progress_label.config(text="Extraction failed!", fg="#e74c3c")
            self.update_status("Extraction failed - see log for details")
            messagebox.showerror("Error", message)

def main():
    root = tk.Tk()
    app = ExtractorGUI(root)
    
    # Center window on screen
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'{width}x{height}+{x}+{y}')
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.cleanup_and_exit()
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        app.cleanup_and_exit()

if __name__ == "__main__":
    main()

