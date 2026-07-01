import argparse
import sys
from pathlib import Path
import datetime

# from src.job_processor import process_application

def main():
    """
    The intuition behind this CLI entry point is to create a clean, 
    interactive loop for the user. It isolates the messy terminal I/O 
    from the clean business logic in your processing modules.
    """
    print("Job Opt: Resume Tailoring Engine")
    
    # 1. Setup argument parsing for structured input
    parser = argparse.ArgumentParser(description="Tailor a master resume to a job description.")
    parser.add_argument("--company", type=str, required=True, help="Name of the company (e.g., 'Google')")
    parser.add_argument("--role", type=str, required=True, help="Job title (e.g., 'Data_Scientist')")
    
    args = parser.parse_args()
    
    print(f"\n[1] Preparing tailored application for {args.role} at {args.company}...")
    
    # 2. Capture multi-line job description
    print("[2] Please paste the job description below.")
    print("    (Press Enter, then Ctrl+D on Mac/Linux or Ctrl+Z on Windows to finish):")
    job_description = sys.stdin.read().strip()
    
    if not job_description:
        print("\nError: Job description cannot be empty. Exiting.")
        return

    # 3. Pass to the orchestrator (Mocked for now)
    print("\n[3] Processing template through LLM and PDF pipeline...")
    # process_application(job_description, args.company, args.role)
    
    # 4. Success state
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    print(f"\n[4] Success! Files saved to data/tailored_outputs/{date_str}_{args.company}_{args.role}.pdf")

if __name__ == "__main__":
    main()
