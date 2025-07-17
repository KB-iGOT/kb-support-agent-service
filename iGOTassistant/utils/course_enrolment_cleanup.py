import json
import copy
import sys
import os
import requests

def clean_course_enrollment_data(data):
    """
    Remove unwanted fields from each enrollment record in the 'courses' array.

    Args:
        data (dict): The user course enrollment response data

    Returns:
        dict: Cleaned data with unwanted fields removed from courses array
    """

    # Fields to remove from each course enrollment record
    unwanted_fields = {
        'description',
        'courseLogoUrl',
        'content',  # Will be removed after extracting course name
        'oldEnrolledDate',
        'addedBy',
        'batch',
        'userId',
        'certificates'
        'lrcProgressDetails',
        'lastContentAccessTime',
        'dateTime',
        'courseId',
        'batchId'
    }

    # Create a deep copy to avoid modifying the original data
    cleaned_data = copy.deepcopy(data)

    # Check if 'result' and 'courses' exist in the data
    # if 'result' in cleaned_data and 'courses' in cleaned_data['result']:
    if True:
        # courses = cleaned_data['result']['courses']
        courses = cleaned_data

        # Clean each course enrollment record
        for course in courses:
            # Extract course name from content before removing it
            if isinstance(course, dict):
                content = course.get('content', {})
                if isinstance(content, dict):
                    course_name = content.get('name')
                    if course_name:
                        course['courseName'] = course_name
                        print(f"Extracted course name: {course_name}")
                    else:
                        print("No course name found in content")
            
            # Remove unwanted fields if they exist
            # print("\n\n\nCOURSE", course)
            for field in unwanted_fields:
                course.pop(field, None)  # pop with None default to avoid KeyError

        print(f"Cleaned {len(courses)} course enrollment records")
        print(f"Removed fields: {', '.join(sorted(unwanted_fields))}")
    else:
        print("Warning: 'result.courses' not found in the provided data")

    # return cleaned_data['result']
    return cleaned_data

def clean_from_json_file(input_file_path, output_file_path=None):
    """
    Load JSON data from file, clean it, and optionally save to output file.

    Args:
        input_file_path (str): Path to input JSON file
        output_file_path (str, optional): Path to save cleaned data. If None, returns data only.

    Returns:
        dict: Cleaned data
    """
    try:
        # Load data from JSON file
        with open(input_file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)

        # Clean the data
        cleaned_data = clean_course_enrollment_data(data)

        # Save to output file if specified
        if output_file_path:
            with open(output_file_path, 'w', encoding='utf-8') as file:
                json.dump(cleaned_data, file, indent=2, ensure_ascii=False)
            print(f"Cleaned data saved to: {output_file_path}")

        return cleaned_data

    except FileNotFoundError:
        print(f"Error: File '{input_file_path}' not found")
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in file '{input_file_path}': {e}")
        return None
    except Exception as e:
        print(f"Error processing file: {e}")
        return None

def fetch_enrollment_data_from_api(user_id, api_key, base_url="https://portal.igotkarmayogi.gov.in"):
    """
    Fetch user enrollment data directly from the API.

    Args:
        user_id (str): User ID for enrollment data
        api_key (str): Authorization token/API key
        base_url (str): Base URL for the API (default: production URL)

    Returns:
        dict: API response data or None if failed
    """
    url = f"{base_url}/api/course/private/v3/user/enrollment/list/{user_id}"

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    try:
        print(f"Fetching enrollment data for user: {user_id}")
        print(f"API URL: {url}")

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            print("✓ API call successful")
            data = response.json()

            # Print some basic info about the response
            if 'result' in data and 'courses' in data['result']:
                course_count = len(data['result']['courses'])
                print(f"✓ Found {course_count} course enrollments")

                return data
        else:
            print(f"✗ API call failed with status code: {response.status_code}")
            print(f"Response: {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"✗ Error making API request: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"✗ Error parsing JSON response: {e}")
        return None
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return None

def clean_and_save_api_data(user_id, api_key, output_file=None, base_url="https://portal.igotkarmayogi.gov.in"):
    """
    Fetch data from API, clean it, and save to file.

    Args:
        user_id (str): User ID for enrollment data
        api_key (str): Authorization token/API key
        output_file (str, optional): Output file path. If None, generates one based on user_id
        base_url (str): Base URL for the API

    Returns:
        dict: Cleaned data or None if failed
    """
    # Fetch data from API
    raw_data = fetch_enrollment_data_from_api(user_id, api_key, base_url)

    if raw_data is None:
        return None

    # Clean the data
    print("\nCleaning enrollment data...")
    cleaned_data = clean_course_enrollment_data(raw_data)

    # Generate output filename if not provided
    if output_file is None:
        output_file = f"enrollment_data_{user_id}_cleaned.json"

    # Save cleaned data
    try:
        with open(output_file, 'w', encoding='utf-8') as file:
            json.dump(cleaned_data, file, indent=2, ensure_ascii=False)
        print(f"✓ Cleaned data saved to: {output_file}")
        return cleaned_data
    except Exception as e:
        print(f"✗ Error saving file: {e}")
        return None

