
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class CommunicationPreferences(BaseModel):
    """
    Represents a user's communication preferences.
    """

    email: bool = True
    sms: bool = True
    push_notifications: bool = True
    model_config = ConfigDict(from_attributes=True)


class Address(BaseModel):
    """
    Represents a user's address.
    """

    street: str
    city: str
    state: str
    zip: str
    model_config = ConfigDict(from_attributes=True)


class Course(BaseModel):
    """
    Enrolled course details
    """
    name: str
    components: str


class Userdetails(BaseModel):
    """
    Represents a registered user details
    """

    userId: str = None
    firstName: str = None
    lastName: str = None
    primaryEmail: str = None
    phone: str = None
    karma_points: int = 0
    # course_history: List[Course] = []
    # communication_preferences: CommunicationPreferences = None
    model_config = ConfigDict(from_attributes=True)

    def to_json(self) -> str:
        """
        Converts the Customer object to a JSON string.

        Returns:
            A JSON string representing the Customer object.
        """
        return self.model_dump_json(indent=4)

    @staticmethod
    def get_customer(userId: str) -> Optional["Userdetails"]:
        """
        Retrieves a customer based on their ID.

        Args:
            customer_id: The ID of the customer to retrieve.

        Returns:
            The Customer object if found, None otherwise.
        """
        # In a real application, this would involve a database lookup.
        # For this example, we'll just return a dummy customer.

        return Userdetails()