# This file is used to create the database and the tables;
# We use sqlalchemy to create the database and the tables;
# We use sqlite as our database, and we use sqlalchemy to connect to the database;
from sqlalchemy import create_engine, Column, String, ForeignKey, PrimaryKeyConstraint
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
# This is the base class of the database, we need to inherit it when we create a table;
Base = declarative_base()

class musicSong(Base):
    __tablename__ = 'musicSong'
    id = Column(String, index=True)
    file_id = Column(String)
    song_name = Column(String)
    __table_args__ = (PrimaryKeyConstraint('id', 'file_id', 'song_name'),)

# Here we use sqlite as our database, and we use sqlalchemy to connect to the database;
engine = create_engine('sqlite:///database.db', echo=False, pool_size=10, max_overflow=10)
# We use sessionmaker to create a session object, and we can use this object to query the database;
seesion = sessionmaker(bind=engine)

# This function is used to get the session object;
def get_session():
    return seesion()

# Create all the tables;
Base.metadata.create_all(engine)