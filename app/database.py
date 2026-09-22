"""
SQLite Database initialization, schema migration, FTS5 virtual tables,
and demo dataset seeding for the Book Search Engine.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
from app import config
from app.search.normalizer import TextNormalizer
from app.search.dictionary import DictionaryManager


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Get an open SQLite database connection with row factory enabled."""
    target_path = db_path or config.DATABASE_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_database(db_path: Optional[Path] = None, seed_data: bool = True) -> sqlite3.Connection:
    """
    Initialize SQLite schema:
    1. books table
    2. book_aliases table
    3. search_logs table
    4. search_dictionary table
    5. synonyms table
    6. Performance indexes
    7. FTS5 full-text search table & synchronization triggers
    8. Seeds 35+ demo books and builds vocabulary dictionary
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Books Table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            author TEXT,
            normalized_author TEXT,
            isbn TEXT UNIQUE,
            description TEXT,
            publisher TEXT,
            category TEXT,
            language TEXT DEFAULT 'en',
            price REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            popularity_score REAL DEFAULT 0.0,
            sales_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # 2. Book Aliases Table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS book_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            source TEXT DEFAULT 'editorial',
            confidence REAL DEFAULT 1.0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE
        );
        """
    )

    # 3. Search Logs Table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS search_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            normalized_query TEXT NOT NULL,
            corrected_query TEXT,
            result_count INTEGER DEFAULT 0,
            clicked_book_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (clicked_book_id) REFERENCES books (id) ON DELETE SET NULL
        );
        """
    )

    # 4. Search Dictionary Table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS search_dictionary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            normalized_word TEXT NOT NULL,
            frequency INTEGER DEFAULT 1,
            source TEXT DEFAULT 'system'
        );
        """
    )

    # 5. Synonyms Table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS synonyms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            synonym TEXT NOT NULL
        );
        """
    )

    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_norm_title ON books(normalized_title);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_norm_author ON books(normalized_author);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_isbn ON books(isbn);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_aliases_norm_alias ON book_aliases(normalized_alias);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_search_logs_norm_query ON search_logs(normalized_query);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_search_dict_norm_word ON search_dictionary(normalized_word);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_synonyms_word ON synonyms(word);")

    # 6. SQLite FTS5 Full-Text Virtual Table
    cursor.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
            title,
            author,
            description,
            category,
            content='books',
            content_rowid='id'
        );
        """
    )

    # FTS5 Triggers to keep external content index in sync
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
            INSERT INTO books_fts(rowid, title, author, description, category)
            VALUES (new.id, new.title, new.author, new.description, new.category);
        END;
        """
    )
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
            INSERT INTO books_fts(books_fts, rowid, title, author, description, category)
            VALUES('delete', old.id, old.title, old.author, old.description, old.category);
        END;
        """
    )
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE ON books BEGIN
            INSERT INTO books_fts(books_fts, rowid, title, author, description, category)
            VALUES('delete', old.id, old.title, old.author, old.description, old.category);
            INSERT INTO books_fts(rowid, title, author, description, category)
            VALUES (new.id, new.title, new.author, new.description, new.category);
        END;
        """
    )

    conn.commit()

    if seed_data:
        # Check if books already exist
        cursor.execute("SELECT COUNT(*) FROM books")
        count = cursor.fetchone()[0]
        if count == 0:
            seed_demo_books(conn)

    return conn


def seed_demo_books(conn: sqlite3.Connection) -> None:
    """Populate demo dataset with 35+ popular books and aliases."""
    cursor = conn.cursor()

    demo_books = [
        {
            "title": "Atomic Habits",
            "author": "James Clear",
            "isbn": "9780735211292",
            "description": "An easy and proven way to build good habits and break bad ones. Tiny changes, remarkable results.",
            "publisher": "Avery / Penguin",
            "category": "Self-Help",
            "price": 399.0,
            "stock": 85,
            "popularity_score": 98.5,
            "sales_count": 14200,
            "aliases": [
                "atomic habbits",
                "atomic habit",
                "atomic habbits book",
                "atomik habits",
                "atomic habits by james clear",
            ],
        },
        {
            "title": "The Psychology of Money",
            "author": "Morgan Housel",
            "isbn": "9780857197689",
            "description": "Timeless lessons on wealth, greed, and happiness doing well with money.",
            "publisher": "Harriman House",
            "category": "Finance & Business",
            "price": 450.0,
            "stock": 64,
            "popularity_score": 96.0,
            "sales_count": 11500,
            "aliases": [
                "psychology of mony",
                "psychology money",
                "psychology of money book",
                "psychology of wealth",
                "morgan housel money",
            ],
        },
        {
            "title": "The Alchemist",
            "author": "Paulo Coelho",
            "isbn": "9780062315007",
            "description": "A magical fable about following your dreams and listening to your heart.",
            "publisher": "HarperOne",
            "category": "Fiction & Philosophy",
            "price": 299.0,
            "stock": 110,
            "popularity_score": 95.0,
            "sales_count": 18900,
            "aliases": [
                "alchmist",
                "alchemist",
                "the alchmist",
                "paulo coelho alchemist",
            ],
        },
        {
            "title": "Rich Dad Poor Dad",
            "author": "Robert T. Kiyosaki",
            "isbn": "9781612680194",
            "description": "What the rich teach their kids about money that the poor and middle class do not.",
            "publisher": "Plata Publishing",
            "category": "Personal Finance",
            "price": 350.0,
            "stock": 75,
            "popularity_score": 93.0,
            "sales_count": 13400,
            "aliases": [
                "rich dad pooor dad",
                "rich dad",
                "poor dad rich dad",
                "rich dad poor dad robert kiyosaki",
            ],
        },
        {
            "title": "Harry Potter and the Philosopher's Stone",
            "author": "J.K. Rowling",
            "isbn": "9780747532743",
            "description": "Harry Potter discovers he is a wizard and attends Hogwarts School of Witchcraft and Wizardry.",
            "publisher": "Bloomsbury",
            "category": "Fantasy & Fiction",
            "price": 499.0,
            "stock": 90,
            "popularity_score": 99.0,
            "sales_count": 25000,
            "aliases": [
                "harry potter",
                "harry poter",
                "harry potter 1",
                "harry potter sorcerers stone",
                "harry potter philosopher stone",
                "harry potter and the sorcerer stone",
            ],
        },
        {
            "title": "Harry Potter and the Chamber of Secrets",
            "author": "J.K. Rowling",
            "isbn": "9780747538493",
            "description": "The second year at Hogwarts School, where the legendary Chamber of Secrets is opened.",
            "publisher": "Bloomsbury",
            "category": "Fantasy & Fiction",
            "price": 499.0,
            "stock": 55,
            "popularity_score": 94.0,
            "sales_count": 16500,
            "aliases": [
                "harry potter 2",
                "chamber of secrets",
                "harry poter chamber of secrets",
            ],
        },
        {
            "title": "Think and Grow Rich",
            "author": "Napoleon Hill",
            "isbn": "9781585424337",
            "description": "The landmark bestseller on wealth creation and the philosophy of personal achievement.",
            "publisher": "TarcherPerigee",
            "category": "Self-Help",
            "price": 280.0,
            "stock": 70,
            "popularity_score": 91.0,
            "sales_count": 9800,
            "aliases": [
                "think grow rich",
                "think and grow rich napoleon hill",
                "think and grow reach",
            ],
        },
        {
            "title": "Ikigai: The Japanese Secret to a Long and Happy Life",
            "author": "Hector Garcia and Francesc Miralles",
            "isbn": "9780143130727",
            "description": "Discover your ikigai and bring meaning and joy to all of your days.",
            "publisher": "Penguin Books",
            "category": "Lifestyle & Philosophy",
            "price": 320.0,
            "stock": 80,
            "popularity_score": 92.5,
            "sales_count": 8700,
            "aliases": [
                "ikigai",
                "ikigai book",
                "japanese secret to long life",
            ],
        },
        {
            "title": "Deep Work",
            "author": "Cal Newport",
            "isbn": "9781455586691",
            "description": "Rules for focused success in a distracted world.",
            "publisher": "Grand Central Publishing",
            "category": "Productivity & Career",
            "price": 420.0,
            "stock": 60,
            "popularity_score": 89.0,
            "sales_count": 7600,
            "aliases": [
                "deep work cal newport",
                "deep work book",
                "deepwork",
            ],
        },
        {
            "title": "The 7 Habits of Highly Effective People",
            "author": "Stephen R. Covey",
            "isbn": "9781982137274",
            "description": "Powerful lessons in personal change and character ethics.",
            "publisher": "Simon & Schuster",
            "category": "Leadership & Self-Help",
            "price": 480.0,
            "stock": 65,
            "popularity_score": 94.5,
            "sales_count": 12800,
            "aliases": [
                "7 habits",
                "seven habits",
                "7 habits highly effective people",
                "seven habits of highly effective people",
                "stephen covey 7 habits",
            ],
        },
        {
            "title": "The Power of Habit",
            "author": "Charles Duhigg",
            "isbn": "9780812981605",
            "description": "Why we do what we do in life and business, exploring the habit loop.",
            "publisher": "Random House",
            "category": "Psychology & Business",
            "price": 399.0,
            "stock": 50,
            "popularity_score": 88.0,
            "sales_count": 6900,
            "aliases": [
                "power of habit",
                "the power of habits",
                "charles duhigg habit",
            ],
        },
        {
            "title": "Sapiens: A Brief History of Humankind",
            "author": "Yuval Noah Harari",
            "isbn": "9780062316097",
            "description": "From a renowned historian comes a groundbreaking narrative of humanity's creation and evolution.",
            "publisher": "Harper",
            "category": "History & Anthropology",
            "price": 550.0,
            "stock": 70,
            "popularity_score": 97.0,
            "sales_count": 15600,
            "aliases": [
                "sapiens",
                "sapien",
                "sapiens a brief history of humankind",
                "yuval noah harari sapiens",
            ],
        },
        {
            "title": "Man's Search for Meaning",
            "author": "Viktor E. Frankl",
            "isbn": "9780807014295",
            "description": "Psychiatrist Viktor Frankl's memoir of surviving Nazi death camps and developing logotherapy.",
            "publisher": "Beacon Press",
            "category": "Psychology & Biography",
            "price": 340.0,
            "stock": 45,
            "popularity_score": 90.0,
            "sales_count": 7200,
            "aliases": [
                "mans search for meaning",
                "search for meaning",
                "viktor frankl",
            ],
        },
        {
            "title": "Thinking, Fast and Slow",
            "author": "Daniel Kahneman",
            "isbn": "9780374533557",
            "description": "Nobel laureate Daniel Kahneman explains the two systems that drive the way we think.",
            "publisher": "Farrar, Straus and Giroux",
            "category": "Behavioral Economics",
            "price": 499.0,
            "stock": 40,
            "popularity_score": 91.5,
            "sales_count": 8300,
            "aliases": [
                "thinking fast and slow",
                "thinking fast slow",
                "daniel kahneman thinking",
            ],
        },
        {
            "title": "Clean Code: A Handbook of Agile Software Craftsmanship",
            "author": "Robert C. Martin",
            "isbn": "9780132350884",
            "description": "A handbook of agile software craftsmanship for writing readable and maintainable software.",
            "publisher": "Prentice Hall",
            "category": "Computer Science & Programming",
            "price": 650.0,
            "stock": 35,
            "popularity_score": 93.0,
            "sales_count": 9100,
            "aliases": [
                "clean code",
                "clean code book",
                "uncle bob clean code",
                "robert martin clean code",
            ],
        },
        {
            "title": "The Pragmatic Programmer",
            "author": "Andrew Hunt and David Thomas",
            "isbn": "9780135957059",
            "description": "Your journey to mastery, filled with practical advice and career best practices for programmers.",
            "publisher": "Addison-Wesley",
            "category": "Computer Science & Programming",
            "price": 680.0,
            "stock": 30,
            "popularity_score": 92.0,
            "sales_count": 7800,
            "aliases": [
                "pragmatic programmer",
                "the pragmatic programmer 20th anniversary",
                "pragmatic programming",
            ],
        },
        {
            "title": "Design Patterns: Elements of Reusable Object-Oriented Software",
            "author": "Erich Gamma, Richard Helm, Ralph Johnson, John Vlissides",
            "isbn": "9780201633610",
            "description": "The classic Gang of Four guide to classic software architectural design patterns.",
            "publisher": "Addison-Wesley",
            "category": "Computer Science & Programming",
            "price": 720.0,
            "stock": 25,
            "popularity_score": 89.5,
            "sales_count": 6400,
            "aliases": [
                "design patterns",
                "gang of four design patterns",
                "gof design patterns",
            ],
        },
        {
            "title": "Zero to One",
            "author": "Peter Thiel and Blake Masters",
            "isbn": "9780804139298",
            "description": "Notes on startups, or how to build the future through breakthrough innovation.",
            "publisher": "Crown Business",
            "category": "Business & Startups",
            "price": 410.0,
            "stock": 55,
            "popularity_score": 87.5,
            "sales_count": 6100,
            "aliases": [
                "zero to one peter thiel",
                "0 to 1",
                "zero to one book",
            ],
        },
        {
            "title": "Can't Hurt Me: Master Your Mind and Defy the Odds",
            "author": "David Goggins",
            "isbn": "9781544512280",
            "description": "Navy SEAL and ultramarathoner shares his astonishing life story and reveals that most of us tap into only 40% of our capabilities.",
            "publisher": "Lioncrest Publishing",
            "category": "Biography & Motivation",
            "price": 460.0,
            "stock": 60,
            "popularity_score": 94.0,
            "sales_count": 10200,
            "aliases": [
                "cant hurt me",
                "david goggins book",
                "cant hurt me david goggins",
            ],
        },
        {
            "title": "Good to Great: Why Some Companies Make the Leap... and Others Don't",
            "author": "Jim Collins",
            "isbn": "9780066620992",
            "description": "Management research study uncovering why certain businesses achieve enduring superiority.",
            "publisher": "HarperBusiness",
            "category": "Business & Leadership",
            "price": 440.0,
            "stock": 42,
            "popularity_score": 86.0,
            "sales_count": 5500,
            "aliases": [
                "good to great",
                "good to great jim collins",
            ],
        },
        {
            "title": "Start with Why: How Great Leaders Inspire Everyone to Take Action",
            "author": "Simon Sinek",
            "isbn": "9781591846444",
            "description": "Discover the golden circle model and why visionary leaders start with why.",
            "publisher": "Portfolio",
            "category": "Leadership & Management",
            "price": 380.0,
            "stock": 50,
            "popularity_score": 88.5,
            "sales_count": 7100,
            "aliases": [
                "start with why",
                "simon sinek start with why",
                "start with why book",
            ],
        },
        {
            "title": "Shoe Dog: A Memoir by the Creator of Nike",
            "author": "Phil Knight",
            "isbn": "9781501135927",
            "description": "The candid and riveting memoir of Nike founder and board chairman Phil Knight.",
            "publisher": "Scribner",
            "category": "Biography & Business",
            "price": 450.0,
            "stock": 48,
            "popularity_score": 91.0,
            "sales_count": 7900,
            "aliases": [
                "shoe dog",
                "shoe dog phil knight",
                "nike book shoe dog",
            ],
        },
        {
            "title": "Steve Jobs",
            "author": "Walter Isaacson",
            "isbn": "9781451648539",
            "description": "The definitive biography of Apple co-founder Steve Jobs based on forty interviews.",
            "publisher": "Simon & Schuster",
            "category": "Biography",
            "price": 520.0,
            "stock": 38,
            "popularity_score": 92.0,
            "sales_count": 8600,
            "aliases": [
                "steve jobs walter isaacson",
                "steve jobs biography",
                "apple steve jobs book",
            ],
        },
        {
            "title": "The Subtle Art of Not Giving a F*ck",
            "author": "Mark Manson",
            "isbn": "9780062457714",
            "description": "A counterintuitive approach to living a good life by choosing what truly matters.",
            "publisher": "HarperOne",
            "category": "Self-Help",
            "price": 390.0,
            "stock": 70,
            "popularity_score": 93.5,
            "sales_count": 11800,
            "aliases": [
                "the subtle art",
                "subtle art",
                "subtle art of not giving a fuck",
                "mark manson subtle art",
            ],
        },
        {
            "title": "Rework",
            "author": "Jason Fried and David Heinemeier Hansson",
            "isbn": "9780307463746",
            "description": "A fresh approach to business, productivity, and entrepreneurship by the creators of Basecamp.",
            "publisher": "Crown Business",
            "category": "Business & Startups",
            "price": 360.0,
            "stock": 35,
            "popularity_score": 85.0,
            "sales_count": 4800,
            "aliases": [
                "rework basecamp",
                "rework jason fried",
                "re work",
            ],
        },
        {
            "title": "Essentialism: The Disciplined Pursuit of Less",
            "author": "Greg McKeown",
            "isbn": "9780804137386",
            "description": "Focus on what is truly vital and eliminate everything that does not contribute.",
            "publisher": "Crown Business",
            "category": "Productivity & Self-Help",
            "price": 410.0,
            "stock": 44,
            "popularity_score": 87.0,
            "sales_count": 5900,
            "aliases": [
                "essentialism",
                "essentialism greg mckeown",
                "disciplined pursuit of less",
            ],
        },
        {
            "title": "Outliers: The Story of Success",
            "author": "Malcolm Gladwell",
            "isbn": "9780316017930",
            "description": "What makes high-achievers different? Exploring cultural, societal, and opportunity factors.",
            "publisher": "Little, Brown and Company",
            "category": "Psychology & Sociology",
            "price": 430.0,
            "stock": 52,
            "popularity_score": 89.0,
            "sales_count": 7300,
            "aliases": [
                "outliers",
                "outliers malcolm gladwell",
                "the 10000 hour rule book",
            ],
        },
        {
            "title": "Educated: A Memoir",
            "author": "Tara Westover",
            "isbn": "9780399590504",
            "description": "An unforgettable memoir about a young girl who, kept out of school, leaves her survivalist family and earns a PhD.",
            "publisher": "Random House",
            "category": "Memoir & Biography",
            "price": 440.0,
            "stock": 40,
            "popularity_score": 91.0,
            "sales_count": 8100,
            "aliases": [
                "educated",
                "tara westover educated",
                "educated memoir",
            ],
        },
        {
            "title": "To Kill a Mockingbird",
            "author": "Harper Lee",
            "isbn": "9780060935467",
            "description": "The Pulitzer Prize-winning classic about justice and childhood in the American South.",
            "publisher": "Harper Perennial",
            "category": "Classic Literature",
            "price": 320.0,
            "stock": 65,
            "popularity_score": 96.0,
            "sales_count": 14500,
            "aliases": [
                "to kill a mockingbird harper lee",
                "mockingbird",
                "atticus finch book",
            ],
        },
        {
            "title": "1984",
            "author": "George Orwell",
            "isbn": "9780451524935",
            "description": "The quintessential dystopian masterpiece of totalitarianism and surveillance.",
            "publisher": "Signet Classic",
            "category": "Classic Literature & Dystopian",
            "price": 270.0,
            "stock": 95,
            "popularity_score": 97.5,
            "sales_count": 19500,
            "aliases": [
                "nineteen eighty four",
                "george orwell 1984",
                "big brother book",
            ],
        },
        {
            "title": "The Great Gatsby",
            "author": "F. Scott Fitzgerald",
            "isbn": "9780743273565",
            "description": "The story of the mysteriously wealthy Jay Gatsby and his love for the beautiful Daisy Buchanan.",
            "publisher": "Scribner",
            "category": "Classic Literature",
            "price": 280.0,
            "stock": 80,
            "popularity_score": 94.0,
            "sales_count": 13200,
            "aliases": [
                "great gatsby",
                "the great gatsby fitzgerald",
                "gatsby",
            ],
        },
        {
            "title": "Norwegian Wood",
            "author": "Haruki Murakami",
            "isbn": "9780375704024",
            "description": "A magnificent coming-of-age story of love, loss, and nostalgia in 1960s Tokyo.",
            "publisher": "Vintage",
            "category": "Literary Fiction",
            "price": 390.0,
            "stock": 46,
            "popularity_score": 89.5,
            "sales_count": 6700,
            "aliases": [
                "norwegian wood haruki murakami",
                "murakami norwegian wood",
            ],
        },
        {
            "title": "Kafka on the Shore",
            "author": "Haruki Murakami",
            "isbn": "9781400079278",
            "description": "A classic work of magical realism following runaway teenager Kafka Tamura.",
            "publisher": "Vintage",
            "category": "Literary Fiction",
            "price": 420.0,
            "stock": 38,
            "popularity_score": 88.0,
            "sales_count": 5800,
            "aliases": [
                "kafka on the shore murakami",
                "kafka shore",
            ],
        },
        {
            "title": "Crime and Punishment",
            "author": "Fyodor Dostoevsky",
            "isbn": "9780140449136",
            "description": "The psychological masterpiece of Raskolnikov and his search for redemption in St. Petersburg.",
            "publisher": "Penguin Classics",
            "category": "Classic Literature",
            "price": 360.0,
            "stock": 45,
            "popularity_score": 92.0,
            "sales_count": 8900,
            "aliases": [
                "crime and punishment dostoevsky",
                "crime and punishment",
            ],
        },
        {
            "title": "The Lean Startup",
            "author": "Eric Ries",
            "isbn": "9780307887894",
            "description": "How today's entrepreneurs use continuous innovation to create radically successful businesses.",
            "publisher": "Crown Business",
            "category": "Business & Startups",
            "price": 450.0,
            "stock": 58,
            "popularity_score": 90.5,
            "sales_count": 8200,
            "aliases": [
                "lean startup",
                "the lean startup eric ries",
                "lean startup book",
            ],
        },
    ]

    for item in demo_books:
        norm_title = TextNormalizer.normalize(item["title"])
        norm_author = TextNormalizer.normalize(item["author"])
        clean_isbn = TextNormalizer.clean_isbn(item["isbn"])

        cursor.execute(
            """
            INSERT INTO books (
                title, normalized_title, author, normalized_author, isbn,
                description, publisher, category, price, stock,
                popularity_score, sales_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["title"],
                norm_title,
                item["author"],
                norm_author,
                clean_isbn,
                item["description"],
                item["publisher"],
                item["category"],
                item["price"],
                item["stock"],
                item["popularity_score"],
                item["sales_count"],
            ),
        )
        book_id = cursor.lastrowid

        # Insert book aliases
        for alias in item.get("aliases", []):
            norm_alias = TextNormalizer.normalize(alias)
            cursor.execute(
                """
                INSERT INTO book_aliases (book_id, alias, normalized_alias, source, confidence)
                VALUES (?, ?, ?, 'editorial', 1.0)
                """,
                (book_id, alias, norm_alias),
            )

    # Insert helpful domain synonyms
    synonym_pairs = [
        ("book", "novel"),
        ("novel", "book"),
        ("money", "wealth"),
        ("wealth", "money"),
        ("finance", "investing"),
        ("investing", "finance"),
        ("habit", "routine"),
        ("routine", "habit"),
        ("author", "writer"),
        ("writer", "author"),
        ("startup", "business"),
        ("business", "startup"),
        ("programming", "coding"),
        ("coding", "programming"),
    ]
    for w, syn in synonym_pairs:
        cursor.execute("INSERT INTO synonyms (word, synonym) VALUES (?, ?)", (w, syn))

    # Commit transactions
    conn.commit()

    # Rebuild search dictionary
    dict_manager = DictionaryManager(conn)
    dict_manager.rebuild_from_database(conn)


if __name__ == "__main__":
    print(f"Initializing database at: {config.DATABASE_PATH}")
    db_conn = init_database(config.DATABASE_PATH, seed_data=True)
    cur = db_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM books")
    b_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM search_dictionary")
    d_count = cur.fetchone()[0]
    print(f"Database initialized successfully! Books: {b_count}, Dictionary entries: {d_count}")
    db_conn.close()
