from sqlalchemy import create_engine, Column, String, ForeignKey, PrimaryKeyConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class apple_music(Base):
    __tablename__ = 'apple_music'
    id = Column(String, index=True)
    fileId = Column(String)
    __table_args__ = (PrimaryKeyConstraint('id', 'fileId'),)

class spotify_music(Base):
    __tablename__ = 'spotify_music'
    id = Column(String, index=True)
    fileId = Column(String)
    __table_args__ = (PrimaryKeyConstraint('id', 'fileId'),)

engine = create_engine('sqlite:///database.db', echo=False, pool_size=10, max_overflow=10)
seesion = sessionmaker(bind=engine)

def get_session():
    return seesion()

Base.metadata.create_all(engine)
