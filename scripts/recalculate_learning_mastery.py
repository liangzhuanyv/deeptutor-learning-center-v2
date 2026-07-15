#!/usr/bin/env python3
"""Recalculate deterministic Learning Center mastery projections without deleting evidence."""
from __future__ import annotations
import argparse
from deeptutor.services.learning_center.mastery import LearningMasteryService

def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args=parser.parse_args()
    print(LearningMasteryService().recalculate(project_id=args.project_id,dry_run=args.dry_run))
if __name__ == '__main__': main()
