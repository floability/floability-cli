"""
Base command class for Floability CLI commands.
"""

from abc import ABC, abstractmethod
import argparse
from typing import Optional, List


class BaseCommand(ABC):
    """
    Abstract base class for all Floability CLI commands.
    
    Each command should implement:
    - name: Command name (e.g., 'run', 'instance')
    - help: Short help text
    - add_arguments(): Register argparse arguments
    - execute(): Run the command
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Command name as it appears in CLI (e.g., 'run', 'instance')."""
        pass
    
    @property
    @abstractmethod
    def help(self) -> str:
        """Short help text shown in 'floability --help'."""
        pass
    
    @abstractmethod
    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Add command-specific arguments to the parser.
        
        Args:
            parser: ArgumentParser to add arguments to
        """
        pass
    
    @abstractmethod
    def execute(self, args: argparse.Namespace, cleanup_manager=None) -> None:
        """
        Execute the command.
        
        Args:
            args: Parsed command-line arguments
            cleanup_manager: Optional cleanup manager for signal handling
        """
        pass
    
    def validate_args(self, args: argparse.Namespace) -> Optional[str]:
        """
        Validate command arguments.
        
        Override this method to add custom validation logic.
        
        Args:
            args: Parsed command-line arguments
            
        Returns:
            Error message string if validation fails, None if valid
        """
        return None
    
    def get_examples(self) -> List[str]:
        """
        Get usage examples for this command.
        
        Returns:
            List of example command strings
        """
        return []
